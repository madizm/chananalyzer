"""
个股缠论分析脚本

交互式输入股票代码，进行缠论分析

使用方法:
    python -m scripts.analyze_stock
"""
import os
import sys
from datetime import datetime

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Common.CEnum import KL_TYPE
from ChanAnalyzer import ChanAnalyzer, MultiChanAnalyzer


def print_banner():
    """打印横幅"""
    print("=" * 60)
    print("           缠论分析工具 - 个股分析")
    print("=" * 60)


def get_stock_code() -> str:
    """获取股票代码输入"""
    while True:
        code = input("\n请输入股票代码（如 000001，输入 q 退出）: ").strip()
        if code.lower() == 'q':
            return None
        if code and code.isdigit():
            # 补全6位代码
            return code.zfill(6)
        print("请输入有效的股票代码（6位数字）")


def get_date_range(prompt: str = "日期范围") -> tuple:
    """获取日期范围"""
    print(f"\n{prompt}（留空使用默认值）")
    begin = input("  开始日期 (格式: YYYY-MM-DD，默认近1年): ").strip()
    end = input("  结束日期 (格式: YYYY-MM-DD，默认至今): ").strip()
    return begin or None, end or None


def get_analysis_type() -> str:
    """获取分析类型"""
    print("\n选择分析类型:")
    print("  1. 日线分析")
    print("  2. 周线分析")
    print("  3. 日线+周线（多周期）")
    print("  4. 自定义")

    while True:
        choice = input("请选择 (1-4，默认 1): ").strip() or "1"
        if choice in ['1', '2', '3', '4']:
            return choice
        print("请输入有效选项 1-4")


def print_analysis(analysis: dict, show_details: bool = False):
    """打印分析结果"""
    if analysis.get("multi"):
        # 多周期结果
        print("\n" + "=" * 60)
        print("多周期分析结果")
        print("=" * 60)

        for level in analysis.get("levels", []):
            kl_type = level.get("kl_type", "")
            print(f"\n【{kl_type}】")
            print_level_summary(level, show_details)
    else:
        # 单周期结果
        print("\n" + "=" * 60)
        print("分析结果")
        print("=" * 60)
        print_level_summary(analysis, show_details)


def print_level_summary(level: dict, show_details: bool = False):
    """打印单级别分析摘要"""
    print(f"  时间范围: {level.get('start_date')} ~ {level.get('end_date')}")
    print(f"  K线数量: {level.get('kline_count')} 根")
    print(f"  当前价格: {level.get('current_price', 0):.2f}")

    # MACD
    macd = level.get('macd')
    if macd:
        print(f"  MACD: {macd.get('macd', 0):.4f}")
        print(f"  DIF: {macd.get('dif', 0):.4f}")
        print(f"  DEA: {macd.get('dea', 0):.4f}")

    # 买卖点
    buy_signals = level.get('buy_signals', [])
    sell_signals = level.get('sell_signals', [])

    print(f"\n  买卖点统计:")
    print(f"    买入点: {len(buy_signals)} 个")
    print(f"    卖出点: {len(sell_signals)} 个")

    if buy_signals:
        print(f"\n  最近买入点:")
        for bs in buy_signals[-3:]:
            print(f"    {bs['type']}: {bs['date']} @ {bs['price']:.2f}")

    if sell_signals:
        print(f"\n  最近卖出点:")
        for bs in sell_signals[-3:]:
            print(f"    {bs['type']}: {bs['date']} @ {bs['price']:.2f}")

    # 笔、线段、中枢统计
    print(f"\n  结构统计:")
    print(f"    笔: {len(level.get('bi_list', []))} 个")
    print(f"    线段: {len(level.get('seg_list', []))} 个")
    print(f"    中枢: {len(level.get('zs_list', []))} 个")

    # 中枢位置
    zs_pos = level.get('zs_position', '')
    print(f"    价格位置: {zs_pos}")

    # 成交量
    vol_analysis = level.get('volume_analysis', {})
    if vol_analysis and 'vol_status' not in str(vol_analysis):
        print(f"\n  成交量: {vol_analysis.get('vol_status', '未知')}")

    if show_details:
        # 显示详细信息
        print("\n" + "-" * 40)
        print("详细信息")

        # 笔列表
        bi_list = level.get('bi_list', [])
        if bi_list:
            print(f"\n  笔列表 (最近5个):")
            for bi in bi_list[-5:]:
                sure = "已确认" if bi.get('is_sure') else "未确认"
                print(f"    {bi['dir']} {bi['start_date']} -> {bi['end_date']}: "
                      f"{bi['start_price']:.2f} -> {bi['end_price']:.2f} ({sure})")

        # 线段列表
        seg_list = level.get('seg_list', [])
        if seg_list:
            print(f"\n  线段列表 (最近3个):")
            for seg in seg_list[-3:]:
                sure = "已确认" if seg.get('is_sure') else "未确认"
                print(f"    {seg['dir']} {seg['start_date']} -> {seg['end_date']}: "
                      f"{seg['start_price']:.2f} -> {seg['end_price']:.2f} "
                      f"({seg['bi_count']}笔, {sure})")

        # 中枢列表
        zs_list = level.get('zs_list', [])
        if zs_list:
            print(f"\n  中枢列表:")
            for zs in zs_list:
                print(f"    中枢{zs['idx']}: {zs['start_date']} -> {zs['end_date']}: "
                      f"区间 [{zs['low']:.2f}, {zs['high']:.2f}], "
                      f"中心 {zs['center']:.2f} ({zs['bi_count']}笔)")


def analyze_single_stock():
    """分析单只股票的主流程"""
    print_banner()

    # 检查 Token
    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        print("\n错误: 未设置 TUSHARE_TOKEN 环境变量")
        print("请先设置 Token:")
        print("  Windows PowerShell: $env:TUSHARE_TOKEN='your_token'")
        print("  Linux/Mac: export TUSHARE_TOKEN='your_token'")
        return

    while True:
        # 获取股票代码
        code = get_stock_code()
        if code is None:
            print("\n退出程序")
            break

        print(f"\n正在分析: {code}")
        print("-" * 40)

        try:
            # 获取分析类型
            analysis_type = get_analysis_type()

            # 获取日期范围
            begin_date, end_date = get_date_range()

            # 获取是否显示详情
            show_details = input("\n显示详细信息? (y/N): ").strip().lower() == 'y'

            print(f"\n正在获取数据并分析...")

            # 执行分析
            if analysis_type == '1':
                # 日线
                analyzer = ChanAnalyzer(
                    code=code,
                    begin_date=begin_date,
                    end_date=end_date,
                    kl_types=KL_TYPE.K_DAY
                )
                analysis = analyzer.get_analysis()

            elif analysis_type == '2':
                # 周线
                analyzer = ChanAnalyzer(
                    code=code,
                    begin_date=begin_date,
                    end_date=end_date,
                    kl_types=KL_TYPE.K_WEEK
                )
                analysis = analyzer.get_analysis()

            elif analysis_type == '3':
                # 多周期
                analyzer = MultiChanAnalyzer(
                    code=code,
                    begin_date=begin_date,
                    end_date=end_date
                )
                analysis = analyzer.get_analysis()

            else:  # choice == '4'
                # 自定义
                print("\n选择周期:")
                print("  1. 1分钟  2. 5分钟  3. 15分钟  4. 30分钟")
                print("  5. 日线  6. 周线  7. 月线")
                period_map = {
                    '1': KL_TYPE.K_1M, '2': KL_TYPE.K_5M, '3': KL_TYPE.K_15M,
                    '4': KL_TYPE.K_30M, '5': KL_TYPE.K_DAY, '6': KL_TYPE.K_WEEK,
                    '7': KL_TYPE.K_MON
                }
                period_choice = input("请选择 (1-7): ").strip() or "5"
                kl_type = period_map.get(period_choice, KL_TYPE.K_DAY)

                analyzer = ChanAnalyzer(
                    code=code,
                    begin_date=begin_date,
                    end_date=end_date,
                    kl_types=kl_type
                )
                analysis = analyzer.get_analysis()

            # 打印结果
            print_analysis(analysis, show_details)

        except Exception as e:
            print(f"\n分析失败: {e}")
            import traceback
            if show_details:
                traceback.print_exc()

        # 询问是否继续
        print("\n" + "=" * 60)
        cont = input("是否继续分析其他股票? (Y/n): ").strip().lower()
        if cont == 'n':
            print("\n退出程序")
            break


if __name__ == "__main__":
    try:
        analyze_single_stock()
    except KeyboardInterrupt:
        print("\n\n程序已中断")
    except Exception as e:
        print(f"\n程序错误: {e}")
        import traceback
        traceback.print_exc()
