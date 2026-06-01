/**
 * CC Invest - Cloudflare Worker Webhook
 * 简化的 Webhook API，适合 Cloudflare Workers 部署
 */

export interface Env {
  WEBHOOK_TOKEN: string;
  // 可以添加更多环境变量
}

const COINGECKO_IDS: Record<string, string> = {
  'BTC': 'bitcoin',
  'BTCUSDT': 'bitcoin',
  'ETH': 'ethereum',
  'ETHUSDT': 'ethereum',
  'BNB': 'binancecoin',
  'BNBUSDT': 'binancecoin',
  'SOL': 'solana',
  'SOLUSDT': 'solana',
  'XRP': 'ripple',
  'XRPUSDT': 'ripple',
  'ADA': 'cardano',
  'ADAUSDT': 'cardano',
  'DOGE': 'dogecoin',
  'DOGEUSDT': 'dogecoin',
  'DOT': 'polkadot',
  'DOTUSDT': 'polkadot',
  'AVAX': 'avalanche-2',
  'AVAXUSDT': 'avalanche-2',
  'LINK': 'chainlink',
  'LINKUSDT': 'chainlink',
  'MATIC': 'matic-network',
  'MATICUSDT': 'matic-network',
  'UNI': 'uniswap',
  'UNIUSDT': 'uniswap',
  'ARB': 'arbitrum',
  'ARBUSDT': 'arbitrum',
  'OP': 'optimism',
  'OPUSDT': 'optimism',
  'PEPE': 'pepe',
  'PEPEUSDT': 'pepe',
  'SHIB': 'shiba-inu',
  'SHIBUSDT': 'shiba-inu',
  'BONK': 'bonk',
  'BONKUSDT': 'bonk',
  'FIL': 'filecoin',
  'FILUSDT': 'filecoin',
  'ATOM': 'cosmos',
  'ATOMUSDT': 'cosmos',
  'LTC': 'litecoin',
  'LTCUSDT': 'litecoin',
  'APT': 'aptos',
  'APTUSDT': 'aptos',
  'INJ': 'injective-protocol',
  'INJUSDT': 'injective-protocol',
  'TIA': 'celestia',
  'TIAUSDT': 'celestia',
  'SUI': 'sui',
  'SUIUSDT': 'sui',
  'NEAR': 'near',
  'NEARUSDT': 'near',
};

// 简单的内存存储（用于演示）
const orderStore: Map<string, any> = new Map();
let orderCounter = 0;

async function fetchPriceFromCoinGecko(symbol: string): Promise<{ price: number; change24h: number } | null> {
  const baseSymbol = symbol.replace('USDT', '').toUpperCase();
  const coinId = COINGECKO_IDS[baseSymbol];
  
  if (!coinId) {
    return null;
  }

  try {
    const response = await fetch(
      `https://api.coingecko.com/api/v3/simple/price?ids=${coinId}&vs_currencies=usd&include_24hr_change=true`,
      { cf: { cacheTtl: 60, cacheEverything: true } } as RequestInit
    );
    
    if (!response.ok) {
      return null;
    }

    const data = await response.json();
    const coinData = data[coinId];
    
    if (coinData) {
      return {
        price: coinData.usd,
        change24h: coinData.usd_24h_change || 0,
      };
    }
  } catch (error) {
    console.error('CoinGecko fetch error:', error);
  }
  
  return null;
}

async function fetchPriceFromDexScreener(symbol: string): Promise<{ price: number; change24h: number } | null> {
  const baseSymbol = symbol.replace('USDT', '').toUpperCase();
  
  try {
    const response = await fetch(
      `https://api.dexscreener.com/latest/dex/search?q=${baseSymbol}`,
      { cf: { cacheTtl: 60, cacheEverything: true } } as RequestInit
    );
    
    if (!response.ok) {
      return null;
    }

    const data = await response.json();
    const pairs = data.pairs;
    
    if (pairs && pairs.length > 0) {
      // 找到流动性最高的交易对
      const validPairs = pairs
        .filter((p: any) => parseFloat(p.liquidity?.usd || '0') > 10000)
        .sort((a: any, b: any) => parseFloat(b.liquidity?.usd || '0') - parseFloat(a.liquidity?.usd || '0'));
      
      if (validPairs.length > 0) {
        const best = validPairs[0];
        return {
          price: parseFloat(best.priceUsd || '0'),
          change24h: parseFloat(best.priceChange?.m24 || '0'),
        };
      }
    }
  } catch (error) {
    console.error('DexScreener fetch error:', error);
  }
  
  return null;
}

async function getPrice(symbol: string): Promise<Response> {
  const normalizedSymbol = symbol.toUpperCase().trim();
  
  // 尝试 CoinGecko
  let priceData = await fetchPriceFromCoinGecko(normalizedSymbol);
  
  // 如果 CoinGecko 失败，尝试 DexScreener
  if (!priceData) {
    priceData = await fetchPriceFromDexScreener(normalizedSymbol);
  }
  
  if (priceData && priceData.price > 0) {
    const baseSymbol = normalizedSymbol.replace('USDT', '');
    
    return new Response(JSON.stringify({
      status: 'success',
      symbol: baseSymbol,
      price: priceData.price,
      change_24h: priceData.change24h,
      price_usd: priceData.price,
      source: priceData === await fetchPriceFromCoinGecko(normalizedSymbol) ? 'coingecko' : 'dexscreener',
      timestamp: new Date().toISOString(),
    }), {
      headers: { 'Content-Type': 'application/json' },
    });
  }
  
  return new Response(JSON.stringify({
    status: 'error',
    message: `Price not found for symbol: ${normalizedSymbol}`,
    timestamp: new Date().toISOString(),
  }), {
    status: 404,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function placeOrder(request: Request, env: Env): Promise<Response> {
  // 验证 webhook token
  const authHeader = request.headers.get('Authorization');
  const expectedToken = env.WEBHOOK_TOKEN || 'default_secret_change_me';
  
  if (authHeader !== `Bearer ${expectedToken}`) {
    return new Response(JSON.stringify({
      status: 'error',
      message: 'Unauthorized',
    }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    const body = await request.json();
    const { symbol, side, quantity, order_type = 'market', price, strategy = 'webhook' } = body;
    
    if (!symbol || !side || !quantity) {
      return new Response(JSON.stringify({
        status: 'error',
        message: 'Missing required fields: symbol, side, quantity',
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    // 模拟订单执行
    const orderId = `ORD_${Date.now()}_${++orderCounter}`;
    const order = {
      order_id: orderId,
      symbol: symbol.toUpperCase(),
      side: side.toUpperCase(),
      quantity: parseFloat(quantity),
      order_type,
      price: price ? parseFloat(price) : null,
      strategy,
      status: 'filled',
      filled_at: new Date().toISOString(),
    };
    
    orderStore.set(orderId, order);

    return new Response(JSON.stringify({
      status: 'success',
      result: order,
      timestamp: new Date().toISOString(),
    }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (error) {
    return new Response(JSON.stringify({
      status: 'error',
      message: 'Invalid request body',
    }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

async function getOrderHistory(limit: number = 20): Promise<Response> {
  const orders = Array.from(orderStore.values())
    .slice(-limit)
    .reverse();

  return new Response(JSON.stringify({
    status: 'success',
    count: orders.length,
    orders,
    timestamp: new Date().toISOString(),
  }), {
    headers: { 'Content-Type': 'application/json' },
  });
}

async function handleSignal(request: Request, env: Env): Promise<Response> {
  // 验证 webhook token
  const authHeader = request.headers.get('Authorization');
  const expectedToken = env.WEBHOOK_TOKEN || 'default_secret_change_me';
  
  if (authHeader !== `Bearer ${expectedToken}`) {
    return new Response(JSON.stringify({
      status: 'error',
      message: 'Unauthorized',
    }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  try {
    const body = await request.json();
    const { symbol, strategy, signal_type, strength = 0.5, confidence = 0.5 } = body;
    
    if (!symbol || !strategy || !signal_type) {
      return new Response(JSON.stringify({
        status: 'error',
        message: 'Missing required fields: symbol, strategy, signal_type',
      }), {
        status: 400,
        headers: { 'Content-Type': 'application/json' },
      });
    }

    const signalId = `SIG_${Date.now()}`;
    const signal = {
      signal_id: signalId,
      symbol: symbol.toUpperCase(),
      strategy,
      signal_type: signal_type.toUpperCase(),
      strength,
      confidence,
      recorded_at: new Date().toISOString(),
    };

    return new Response(JSON.stringify({
      status: 'recorded',
      signal_id: signalId,
      signal,
      timestamp: new Date().toISOString(),
    }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch (error) {
    return new Response(JSON.stringify({
      status: 'error',
      message: 'Invalid request body',
    }), {
      status: 400,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;

    // CORS 预检请求
    if (method === 'OPTIONS') {
      return new Response(null, {
        status: 204,
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type, Authorization',
        },
      });
    }

    // 路由处理
    try {
      // 价格查询 GET /webhooks/price/:symbol
      const priceMatch = path.match(/^\/webhooks\/price\/(.+)$/);
      if (priceMatch && method === 'GET') {
        return getPrice(priceMatch[1]);
      }

      // 下单 POST /webhooks/place_order
      if (path === '/webhooks/place_order' && method === 'POST') {
        return placeOrder(request, env);
      }

      // 信号记录 POST /webhooks/signal
      if (path === '/webhooks/signal' && method === 'POST') {
        return handleSignal(request, env);
      }

      // 订单历史 GET /webhooks/orders
      if (path === '/webhooks/orders' && method === 'GET') {
        const limit = parseInt(url.searchParams.get('limit') || '20');
        return getOrderHistory(limit);
      }

      // 健康检查 GET /health
      if (path === '/health' && method === 'GET') {
        return new Response(JSON.stringify({
          status: 'healthy',
          service: 'cc-invest-worker',
          version: '1.0.0',
          timestamp: new Date().toISOString(),
        }), {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        });
      }

      // API 文档 GET /docs
      if (path === '/docs' && method === 'GET') {
        return new Response(`
<!DOCTYPE html>
<html>
<head>
  <title>CC Invest Webhook API</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
    h1 { color: #f6821f; }
    h2 { color: #333; margin-top: 30px; }
    code { background: #f4f4f4; padding: 2px 6px; border-radius: 4px; }
    .endpoint { background: #f9f9f9; padding: 15px; margin: 10px 0; border-radius: 8px; }
    .method { font-weight: bold; color: #fff; padding: 4px 8px; border-radius: 4px; }
    .get { background: #61affe; }
    .post { background: #49cc90; }
  </style>
</head>
<body>
  <h1>📊 CC Invest Webhook API</h1>
  <p>Cloudflare Workers 部署的简化版交易 Webhook</p>

  <h2>认证</h2>
  <p>在请求头中添加: <code>Authorization: Bearer YOUR_WEBHOOK_TOKEN</code></p>

  <h2>端点</h2>
  
  <div class="endpoint">
    <span class="method get">GET</span> <code>/health</code>
    <p>健康检查</p>
  </div>

  <div class="endpoint">
    <span class="method get">GET</span> <code>/webhooks/price/:symbol</code>
    <p>获取代币价格</p>
    <p>示例: <code>/webhooks/price/BTCUSDT</code></p>
  </div>

  <div class="endpoint">
    <span class="method post">POST</span> <code>/webhooks/place_order</code>
    <p>下单 (模拟)</p>
    <pre>${JSON.stringify({
      symbol: "BTCUSDT",
      side: "BUY",
      quantity: 0.1,
      order_type: "market",
      strategy: "webhook"
    }, null, 2)}</pre>
  </div>

  <div class="endpoint">
    <span class="method post">POST</span> <code>/webhooks/signal</code>
    <p>记录交易信号</p>
    <pre>${JSON.stringify({
      symbol: "ETHUSDT",
      strategy: "rsi_divergence",
      signal_type: "BUY",
      strength: 0.8,
      confidence: 0.75
    }, null, 2)}</pre>
  </div>

  <div class="endpoint">
    <span class="method get">GET</span> <code>/webhooks/orders?limit=20</code>
    <p>获取订单历史</p>
  </div>

  <h2>注意</h2>
  <p>⚠️ 这是简化版本，仅支持基本功能。</p>
  <p>完整功能请部署完整的 FastAPI 后端到 Render/Railway。</p>
</body>
</html>
        `, {
          headers: { 'Content-Type': 'text/html' },
        });
      }

      // 根路径
      if (path === '/' && method === 'GET') {
        return new Response(JSON.stringify({
          service: 'CC Invest Webhook API',
          version: '1.0.0',
          docs: '/docs',
          health: '/health',
        }), {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
          },
        });
      }

      return new Response(JSON.stringify({
        status: 'error',
        message: 'Endpoint not found',
      }), {
        status: 404,
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
        },
      });
    } catch (error) {
      return new Response(JSON.stringify({
        status: 'error',
        message: 'Internal server error',
        error: String(error),
      }), {
        status: 500,
        headers: { 'Content-Type': 'application/json' },
      });
    }
  },
} satisfies ExportedHandler<Env>;
