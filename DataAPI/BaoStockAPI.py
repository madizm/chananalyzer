import baostock as bs

from Common.CEnum import AUTYPE, DATA_FIELD, KL_TYPE
from Common.CTime import CTime
from Common.func_util import kltype_lt_day, str2float
from KLine.KLine_Unit import CKLine_Unit

from .CommonStockAPI import CCommonStockApi


def create_item_dict(data, column_name):
    for i in range(len(data)):
        data[i] = parse_time_column(data[i]) if i == 0 else str2float(data[i])
    return dict(zip(column_name, data))


def parse_time_column(inp):
    # 20210902113000000
    # 2021-09-13
    if len(inp) == 10:
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = minute = 0
    elif len(inp) == 17:
        year = int(inp[:4])
        month = int(inp[4:6])
        day = int(inp[6:8])
        hour = int(inp[8:10])
        minute = int(inp[10:12])
    elif len(inp) == 19:
        year = int(inp[:4])
        month = int(inp[5:7])
        day = int(inp[8:10])
        hour = int(inp[11:13])
        minute = int(inp[14:16])
    else:
        raise Exception(f"unknown time column from baostock:{inp}")
    return CTime(year, month, day, hour, minute)


def GetColumnNameFromFieldList(fileds: str):
    _dict = {
        "time": DATA_FIELD.FIELD_TIME,
        "date": DATA_FIELD.FIELD_TIME,
        "open": DATA_FIELD.FIELD_OPEN,
        "high": DATA_FIELD.FIELD_HIGH,
        "low": DATA_FIELD.FIELD_LOW,
        "close": DATA_FIELD.FIELD_CLOSE,
        "volume": DATA_FIELD.FIELD_VOLUME,
        "amount": DATA_FIELD.FIELD_TURNOVER,
        "turn": DATA_FIELD.FIELD_TURNRATE,
    }
    return [_dict[x] for x in fileds.split(",")]


class CBaoStock(CCommonStockApi):
    is_connect = None

    def __init__(
        self,
        code,
        k_type=KL_TYPE.K_DAY,
        begin_date=None,
        end_date=None,
        autype=AUTYPE.QFQ,
    ):
        normalized_code = self._normalize_code_for_baostock(code)
        super(CBaoStock, self).__init__(
            normalized_code, k_type, begin_date, end_date, autype
        )

    @staticmethod
    def _normalize_code_for_baostock(code: str) -> str:
        """
        统一转换为 BaoStock 可识别的 9 位股票代码格式：
        - 6位纯数字: 600000 -> sh.600000, 000001 -> sz.000001
        - 9位带点格式: sh.600000 / sz.000001
        - 8位前缀无点: sh600000 / sz000001
        """
        if code is None:
            raise ValueError("股票代码不能为空")

        raw_code = str(code).strip()
        code_lower = raw_code.lower()

        # 已是标准格式
        if (
            len(code_lower) == 9
            and code_lower[2] == "."
            and code_lower[:2] in ("sh", "sz")
            and code_lower[3:].isdigit()
        ):
            return code_lower

        # 无点前缀格式
        if (
            len(code_lower) == 8
            and code_lower[:2] in ("sh", "sz")
            and code_lower[2:].isdigit()
        ):
            return f"{code_lower[:2]}.{code_lower[2:]}"

        # 6位纯数字格式
        if len(code_lower) == 6 and code_lower.isdigit():
            market = "sh" if code_lower.startswith("6") else "sz"
            return f"{market}.{code_lower}"

        raise ValueError(
            f"无效股票代码格式: {raw_code}，请使用 6 位数字或 sh.600000/sz.000001 格式"
        )

    def get_kl_data(self):
        # 天级别以上才有详细交易信息
        if kltype_lt_day(self.k_type):
            if not self.is_stock:
                raise Exception("没有获取到数据，注意指数是没有分钟级别数据的！")
            fields = "time,open,high,low,close"
        else:
            fields = "date,open,high,low,close,volume,amount,turn"
        autype_dict = {AUTYPE.QFQ: "2", AUTYPE.HFQ: "1", AUTYPE.NONE: "3"}
        adjustflag = autype_dict.get(self.autype, autype_dict[AUTYPE.QFQ])
        rs = bs.query_history_k_data_plus(
            code=self.code,
            fields=fields,
            start_date=self.begin_date,
            end_date=self.end_date,
            frequency=self.__convert_type(),
            adjustflag=adjustflag,
        )
        if rs.error_code != "0":
            raise Exception(rs.error_msg)
        while rs.error_code == "0" and rs.next():
            yield CKLine_Unit(
                create_item_dict(rs.get_row_data(), GetColumnNameFromFieldList(fields))
            )

    def SetBasciInfo(self):
        rs = bs.query_stock_basic(code=self.code)
        if rs.error_code != "0":
            raise Exception(rs.error_msg)
        if not rs.next():
            self.name = self.code
            self.is_stock = False
            raise Exception(
                f"BaoStock 未返回股票基本信息，可能是指数/基金/无效代码: {self.code}"
            )
        row = rs.get_row_data()
        if len(row) < 6:
            self.name = self.code
            self.is_stock = False
            raise Exception(
                f"BaoStock 股票基本信息字段异常，可能是指数/基金/无效代码: {self.code}"
            )
        code, code_name, ipoDate, outDate, stock_type, status = row
        self.name = code_name
        self.is_stock = stock_type == "1"

    @classmethod
    def do_init(cls):
        if not cls.is_connect:
            cls.is_connect = bs.login()

    @classmethod
    def do_close(cls):
        if cls.is_connect:
            bs.logout()
            cls.is_connect = None

    def __convert_type(self):
        _dict = {
            KL_TYPE.K_DAY: "d",
            KL_TYPE.K_WEEK: "w",
            KL_TYPE.K_MON: "m",
            KL_TYPE.K_5M: "5",
            KL_TYPE.K_15M: "15",
            KL_TYPE.K_30M: "30",
            KL_TYPE.K_60M: "60",
        }
        return _dict[self.k_type]
