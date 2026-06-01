# =====================================================
# CC Invest - 时间工具模块
# 统一处理中国上海时区
# =====================================================

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

# 上海时区常量
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
UTC_TZ = timezone.utc

# 时区显示名称
SHANGHAI_TZ_NAME = "CST"
UTC_TZ_NAME = "UTC"


def get_shanghai_now() -> datetime:
    """
    获取当前上海时间（带时区信息）
    
    Returns:
        datetime: 当前上海时间，格式: 2024-05-14 10:00:00 CST
    """
    return datetime.now(SHANGHAI_TZ)


def get_utc_now() -> datetime:
    """
    获取当前 UTC 时间（带时区信息）
    
    Returns:
        datetime: 当前 UTC 时间，格式: 2024-05-14 02:00:00 UTC
    """
    return datetime.now(UTC_TZ)


def to_shanghai_time(dt: datetime) -> datetime:
    """
    将任意时区的时间转换为上海时间
    
    Args:
        dt: 输入的时间（可以是 naive 或 aware）
    
    Returns:
        datetime: 上海时间
    """
    if dt.tzinfo is None:
        # naive 时间，假设为 UTC
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(SHANGHAI_TZ)


def to_utc_time(dt: datetime) -> datetime:
    """
    将任意时区的时间转换为 UTC 时间
    
    Args:
        dt: 输入的时间
    
    Returns:
        datetime: UTC 时间
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    return dt.astimezone(UTC_TZ)


def format_shanghai(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化为上海时间的字符串
    
    Args:
        dt: 输入的时间
        fmt: 日期格式
    
    Returns:
        str: 格式化的字符串
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    shanghai_dt = dt.astimezone(SHANGHAI_TZ)
    return f"{shanghai_dt.strftime(fmt)} {SHANGHAI_TZ_NAME}"


def format_utc(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化为 UTC 时间的字符串
    
    Args:
        dt: 输入的时间
        fmt: 日期格式
    
    Returns:
        str: 格式化的字符串
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC_TZ)
    utc_dt = dt.astimezone(UTC_TZ)
    return f"{utc_dt.strftime(fmt)} {UTC_TZ_NAME}"


def get_timestamp() -> datetime:
    """
    获取带时区信息的时间戳（用于数据库存储）
    统一使用 UTC 存储
    
    Returns:
        datetime: UTC 时间（用于数据库存储）
    """
    return datetime.now(UTC_TZ)


# =====================================================
# 测试函数
# =====================================================

if __name__ == "__main__":
    print("=" * 60)
    print("⏰ 时间工具模块测试")
    print("=" * 60)
    print()
    
    # 测试获取当前时间
    print("📅 当前时间测试:")
    print(f"   上海时间: {format_shanghai(get_utc_now())}")
    print(f"   UTC 时间: {format_utc(get_utc_now())}")
    print()
    
    # 测试时区转换
    print("🔄 时区转换测试:")
    utc_now = get_utc_now()
    shanghai_now = get_shanghai_now()
    print(f"   UTC: {format_utc(utc_now)}")
    print(f"   上海: {format_shanghai(shanghai_now)}")
    
    # 验证时差
    from datetime import timedelta
    diff = shanghai_now.replace(tzinfo=None) - utc_now.replace(tzinfo=None)
    hours = diff.total_seconds() / 3600
    print(f"   时差: {hours:.0f} 小时 (应为 8 小时)")
    
    print()
    print("=" * 60)
    
    if abs(hours - 8) < 0.1:
        print("✅ 时区转换正确!")
    else:
        print("❌ 时区转换错误!")
    
    print("=" * 60)