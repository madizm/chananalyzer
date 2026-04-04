import json

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE
from Plot.AnimatePlotDriver import CAnimateDriver
from Plot.PlotDriver import CPlotDriver


def _serialize_level(chan: CChan, level_idx: int) -> dict:
    kl_data = chan[level_idx]
    kl_type = chan.lv_list[level_idx]

    if len(kl_data.lst) == 0:
        return {
            "kl_type": str(kl_type),
            "kline_count": 0,
            "error": "no kline data",
        }

    first_klc = kl_data.lst[0]
    last_klc = kl_data.lst[-1]
    first_klu = first_klc.lst[0]
    last_klu = last_klc.lst[-1]

    bi_list = []
    for bi in kl_data.bi_list:
        bi_list.append(
            {
                "idx": bi.idx,
                "dir": "up" if bi.is_up() else "down",
                "start_date": bi.get_begin_klu().time.to_str(),
                "end_date": bi.get_end_klu().time.to_str(),
                "start_price": bi.get_begin_val(),
                "end_price": bi.get_end_val(),
                "is_sure": bi.is_sure,
            }
        )

    seg_list = []
    for seg in kl_data.seg_list:
        seg_list.append(
            {
                "idx": seg.idx,
                "dir": "up" if seg.is_up() else "down",
                "start_date": seg.get_begin_klu().time.to_str(),
                "end_date": seg.get_end_klu().time.to_str(),
                "start_price": seg.get_begin_val(),
                "end_price": seg.get_end_val(),
                "bi_count": seg.cal_bi_cnt(),
                "is_sure": seg.is_sure,
            }
        )

    zs_list = []
    for zs in kl_data.zs_list:
        zs_list.append(
            {
                "idx": zs.begin_bi.idx,
                "start_date": zs.begin_bi.get_begin_klu().time.to_str(),
                "end_date": zs.end_bi.get_end_klu().time.to_str(),
                "high": zs.high,
                "low": zs.low,
                "center": zs.mid,
                "bi_count": zs.end_bi.idx - zs.begin_bi.idx + 1,
            }
        )

    buy_signals = []
    sell_signals = []
    for bsp in kl_data.bs_point_lst.getSortedBspList():
        signal = {
            "type": bsp.type2str(),
            "is_buy": bsp.is_buy,
            "date": bsp.klu.time.to_str(),
            "price": bsp.klu.close,
            "klu_idx": bsp.klu.idx,
        }
        if bsp.is_buy:
            buy_signals.append(signal)
        else:
            sell_signals.append(signal)

    return {
        "kl_type": str(kl_type),
        "start_date": first_klu.time.to_str(),
        "end_date": last_klu.time.to_str(),
        "kline_count": len(kl_data.lst),
        "current_price": last_klu.close,
        "bi_list": bi_list,
        "seg_list": seg_list,
        "zs_list": zs_list,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
    }


def _build_structured_output(chan: CChan, code: str, begin_time: str, end_time: str) -> dict:
    levels = [_serialize_level(chan, i) for i in range(len(chan.lv_list))]
    return {
        "code": code,
        "begin_time": begin_time,
        "end_time": end_time,
        "multi": len(levels) > 1,
        "levels": levels,
    }

if __name__ == "__main__":
    code = "000062"
    begin_time = "2025-12-25"
    end_time = "2026-03-03"
    data_src = DATA_SRC.TDX
    # 如果已安装通达信 Python 插件，可切换为 DATA_SRC.TDX
    # code 建议使用 6 位代码（如 "000001"）或后缀格式（如 "000001.SZ"）
    # data_src = DATA_SRC.TDX
    lv_list = [KL_TYPE.K_DAY, KL_TYPE.K_30M]

    config = CChanConfig({
        "bi_strict": True,
        "trigger_step": False,
        "skip_step": 0,
        "divergence_rate": float("inf"),
        "bsp2_follow_1": False,
        "bsp3_follow_1": False,
        "min_zs_cnt": 0,
        "bs1_peak": False,
        "macd_algo": "peak",
        "bs_type": '1,2,3a,1p,2s,3b',
        "print_warning": True,
        "zs_algo": "normal",
    })

    plot_config = {
        "plot_kline": True,
        "plot_kline_combine": True,
        "plot_bi": True,
        "plot_seg": True,
        "plot_eigen": False,
        "plot_zs": True,
        "plot_macd": False,
        "plot_mean": False,
        "plot_channel": False,
        "plot_bsp": True,
        "plot_extrainfo": False,
        "plot_demark": False,
        "plot_marker": False,
        "plot_rsi": False,
        "plot_kdj": False,
    }

    plot_para = {
        "seg": {
            # "plot_trendline": True,
        },
        "bi": {
            # "show_num": True,
            # "disp_end": True,
        },
        "figure": {
            "x_range": 200,
        },
        "marker": {
            # "markers": {  # text, position, color
            #     '2023/06/01': ('marker here', 'up', 'red'),
            #     '2023/06/08': ('marker here', 'down')
            # },
        }
    }
    chan = CChan(
        code=code,
        begin_time=begin_time,
        end_time=end_time,
        data_src=data_src,
        lv_list=lv_list,
        config=config,
        autype=AUTYPE.QFQ,
    )

    structured = _build_structured_output(chan, code, begin_time, end_time)
    print(json.dumps(structured, ensure_ascii=False, indent=2, default=str))

    if not config.trigger_step:
        plot_driver = CPlotDriver(
            chan,
            plot_config=plot_config,
            plot_para=plot_para,
        )
        plot_driver.figure.show()
        plot_driver.save2img("./test.png")
    else:
        CAnimateDriver(
            chan,
            plot_config=plot_config,
            plot_para=plot_para,
        )
