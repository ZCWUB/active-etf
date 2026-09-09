"""各投信 PCF／投資組合明細轉接器。

每個 adapter 需提供：
    ISSUER: str                     對應 universe.json 的 issuer 欄位
    discover(sess) -> {etf_code: internal_id}
    fetch(sess, code, internal_id) -> snapshot dict

snapshot 統一格式見 docs 或 fetch_pcf.py 的 validate()。
揭露基礎分兩種：
    basis="fund"    投信直接公告全基金持股（現金申贖制居多）
    basis="basket"  只公告每一申購買回基數的實物籃子，需用 fund_units/unit_size 放大
"""
from . import (ab, capital, cathay, ctbc, fubon, fuhhwa, jpm, kgi, mega, nomura,
               sinopac, uni, yuanta)

ADAPTERS = [uni, capital, yuanta, fuhhwa, cathay, ctbc, fubon, kgi, nomura, ab, jpm,
            sinopac, mega]
BY_ISSUER = {m.ISSUER: m for m in ADAPTERS}
