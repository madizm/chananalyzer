"""
缠论分析结果格式化器

按照改进意见的格式输出分析报告
"""
from typing import Any


def format_summary(analysis: dict[str, Any], add_header: bool = True) -> str:
    """
    格式化单周期分析结果为文本摘要（按改进意见格式）

    Args:
        analysis: get_analysis() 返回的分析结果
        add_header: 是否添加标题（多周期分析时设为False）

    Returns:
        格式化的文本摘要
    """
    lines = []

    # 标题（仅在单周期分析时添加）
    if add_header:
        kl_type = analysis.get("kl_type", "")
        if "60分钟" in kl_type:
            kl_type_code = "H1"
        elif "周线" in kl_type:
            kl_type_code = "W1"
        else:
            kl_type_code = "D1"
        lines.append("============================================================")
        lines.append(f"## {analysis['code']} - {kl_type_code}")
        lines.append("")
        lines.append("")

    # 最新K线
    lines.append("### 最新K线")
    macd = analysis.get("macd")
    latest_bi = analysis.get("latest", {}).get("bi")
    if macd:
        lines.append(f"- 时间: {analysis['end_date']}")
        if latest_bi:
            lines.append(f"- 开盘价: {latest_bi['start_price']:.2f}")
        lines.append(f"- 收盘价: {analysis['current_price']:.2f}")
        lines.append(f"- MACD: {macd['macd']:.2f}")
        lines.append(f"- DIF: {macd['dif']:.2f}")
        lines.append(f"- DEA: {macd['dea']:.2f}")
    else:
        lines.append(f"- 时间: {analysis['end_date']}")
        if latest_bi:
            lines.append(f"- 开盘价: {latest_bi['start_price']:.2f}")
        lines.append(f"- 收盘价: {analysis['current_price']:.2f}")
    lines.append("")

    # 笔分析
    lines.append("### 笔分析")
    bi_list = analysis["bi_list"]
    for bi in bi_list[-3:]:  # 显示最近3笔
        macd_str = f", MACD={bi['macd']:.2f}" if bi.get('macd') else ""
        lines.append(f"- 笔{bi['idx']}: {bi['dir']}, 起点={bi['start_price']:.2f}, 终点={bi['end_price']:.2f}{macd_str}")

    if bi_list:
        current_bi_dir = bi_list[-1]['dir']
        lines.append(f"")
        lines.append(f"当前笔: {current_bi_dir}")
    lines.append("")

    # 线段分析
    lines.append("### 线段分析")
    seg_list = analysis["seg_list"]
    for seg in seg_list[-2:]:  # 显示最近2个线段
        lines.append(f"- 线段{seg['idx']}: {seg['dir']}, 起点={seg['start_price']:.2f}, 终点={seg['end_price']:.2f}")

    if seg_list:
        current_seg_dir = seg_list[-1]['dir']
        lines.append(f"")
        lines.append(f"当前线段: {current_seg_dir}")
    lines.append("")

    # 中枢分析
    lines.append("### 中枢分析")
    zs_list = analysis["zs_list"]
    for zs in zs_list[-3:]:  # 显示最近3个中枢
        lines.append(f"- 中枢{zs['idx']}: 高={zs['high']:.2f}, 低={zs['low']:.2f}")

    zs_position = analysis.get("zs_position", "")
    if zs_list:
        current_price = analysis['current_price']
        if "中枢上方" in zs_position:
            position_desc = "中枢上方（强势）"
        elif "中枢下方" in zs_position:
            position_desc = "中枢下方（弱势）"
        else:
            position_desc = zs_position
        lines.append(f"")
        lines.append(f"当前价格: {current_price:.2f}, 相对中枢位置: {position_desc}")
    else:
        lines.append("")
        lines.append(f"当前价格: {analysis['current_price']:.2f}")
    lines.append("")

    # 买卖点信号
    lines.append("### 买卖点信号")
    buy_signals = analysis.get("buy_signals", [])
    sell_signals = analysis.get("sell_signals", [])

    # 显示最近的买入信号
    if buy_signals:
        for bs in buy_signals[-3:]:
            type_name = _format_bs_type(bs['type'])
            lines.append(f"- 买入信号: 类型={bs['type']}, 时间={bs['date']}, 价格={bs['price']:.2f}")

    # 显示最近的卖出信号
    if sell_signals:
        for bs in sell_signals[-3:]:
            type_name = _format_bs_type(bs['type'])
            lines.append(f"- 卖出信号: 类型={bs['type']}, 时间={bs['date']}, 价格={bs['price']:.2f}")

    if not buy_signals and not sell_signals:
        lines.append("- 未检测到买卖点信号")
    lines.append("")

    # 成交量分析
    lines.append("### 成交量分析")
    vol_analysis = analysis.get("volume_analysis")
    if vol_analysis and "status" not in vol_analysis:
        lines.append(f"- 当前成交量: {vol_analysis['current_vol']:.2f}")
        lines.append(f"- 5周期均量: {vol_analysis['avg_vol']:.2f}")
        lines.append(f"- 量能状态: {vol_analysis['vol_status']}")

        k_vol_price = vol_analysis.get("k_vol_price", [])
        if k_vol_price:
            lines.append(f"- 最近5根K线量价:")
            for i, kvp in enumerate(k_vol_price):
                lines.append(f"  K{i+1}: {kvp['desc']}")

        vol_price_rel = vol_analysis.get("vol_price_rel", "")
        if vol_price_rel:
            lines.append(f"- 量价配合: {vol_price_rel}")
    else:
        lines.append("- 成交量数据不足")
    lines.append("")

    lines.append("")

    return "\n".join(lines)


def format_multi_summary(analysis: dict[str, Any]) -> str:
    """
    格式化多周期分析结果为文本摘要（按改进意见格式）

    Args:
        analysis: get_analysis() 返回的多周期分析结果

    Returns:
        格式化的多周期文本摘要
    """
    lines = []

    for level_data in analysis['levels']:
        kl_type = level_data.get("kl_type", "")
        kl_type_code = "H1" if "60分钟" in kl_type else "D1" if "日线" in kl_type else "W1"
        code = analysis['code']

        lines.append("============================================================")
        lines.append(f"## {code} - {kl_type_code}")
        lines.append("")

        if 'error' in level_data:
            lines.append(f"错误: {level_data['error']}")
            lines.append("")
            lines.append("")
            continue

        # 使用单周期格式（不添加标题，因为已经在上面添加了）
        level_analysis = {**level_data, "code": code}
        lines.append(format_summary(level_analysis, add_header=False))

    return "\n".join(lines)


def _format_bs_type(type_str: str) -> str:
    """格式化买卖点类型"""
    type_map = {
        "1": "1",
        "1p": "1p",
        "2": "2",
        "2s": "2s",
        "3a": "3a",
        "3b": "3b",
    }
    return type_map.get(type_str.split(",")[0] if "," in type_str else type_str, type_str)


def _generate_conclusion(analysis: dict[str, Any]) -> str:
    """生成综合判断（保留兼容性）"""
    current_price = analysis['current_price']
    latest_bi = analysis['latest'].get('bi')
    latest_seg = analysis['latest'].get('seg')
    latest_zs = analysis['latest'].get('zs')
    bs_points = analysis.get("buy_signals", []) + analysis.get("sell_signals", [])

    conclusions = []

    # 当前状态
    if latest_bi:
        bi_dir = latest_bi['dir']
        conclusions.append(f"当前为{bi_dir}笔")

    # 线段趋势
    if latest_seg:
        seg_dir = latest_seg['dir']
        conclusions.append(f"处于{seg_dir}线段中")

    # 中枢状态
    zs_position = analysis.get("zs_position", "")
    if "中枢上方" in zs_position:
        conclusions.append("处于中枢上方强势区域")
    elif "中枢下方" in zs_position:
        conclusions.append("处于中枢下方弱势区域")
    elif "中枢内部" in zs_position:
        conclusions.append("处于中枢震荡区域")

    # 买卖点判断
    if bs_points:
        latest_bs = bs_points[-1]
        bs_type = _format_bs_type(latest_bs['type'])
        bs_dir = "买入" if latest_bs['is_buy'] else "卖出"
        conclusions.append(f"最近出现{bs_type}类{bs_dir}信号")

    # 如果没有结论
    if not conclusions:
        return "数据不足，暂无法做出判断"

    return "，".join(conclusions) + "。"


def format_for_deepseek(analysis: dict[str, Any]) -> str:
    """
    格式化为适合发送给 DeepSeek 的文本

    Args:
        analysis: 分析结果

    Returns:
        简洁的文本描述
    """
    lines = []

    lines.append(f"股票{analysis['code']}的缠论分析:")
    lines.append(f"分析周期: {analysis.get('start_date', '')} 至 {analysis.get('end_date', '')}")
    lines.append(f"当前价格: {analysis['current_price']:.2f}元")

    # MACD
    macd = analysis.get("macd")
    if macd:
        lines.append(f"MACD: {macd['macd']:.2f}, DIF: {macd['dif']:.2f}, DEA: {macd['dea']:.2f}")

    # 笔
    if analysis['bi_list']:
        latest_bi = analysis['bi_list'][-1]
        lines.append(f"最新{latest_bi['dir']}笔: {latest_bi['start_price']:.2f} → {latest_bi['end_price']:.2f}")

    # 中枢
    if analysis['zs_list']:
        latest_zs = analysis['zs_list'][-1]
        zs_position = analysis.get("zs_position", "")
        lines.append(f"最新中枢: [{latest_zs['low']:.2f}, {latest_zs['high']:.2f}], {zs_position}")

    # 买卖点
    buy_signals = analysis.get("buy_signals", [])
    sell_signals = analysis.get("sell_signals", [])

    if buy_signals:
        bs = buy_signals[-1]
        lines.append(f"最近买入信号: {bs['type']}类 @ {bs['date']} 价格{bs['price']:.2f}元")
    if sell_signals:
        bs = sell_signals[-1]
        lines.append(f"最近卖出信号: {bs['type']}类 @ {bs['date']} 价格{bs['price']:.2f}元")

    return "\n".join(lines)
