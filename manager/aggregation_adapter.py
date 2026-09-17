"""集約アダプタのインターフェース定義。

契約:
    入力: manager/record.py の Reading データクラスのインスタンスのリスト。
    出力: AdapterResult データクラス。
    エラー: アダプタの実装側で例外を投げず、AdapterResult(success=False) で表現すること。
        呼び出し側は try/except ではなく戻り値の success / failed_readings /
        error_message を見て成否を判断する。

注意:
    このファイルにはURL・認証情報・実際の通信コード (requests / http.client 等)
    を一切含めないこと。実接続は将来の具象アダプタで実装し、このモジュールは
    差し替え可能な境界の定義と、何もしない参照実装 (NullAdapter) のみを持つ。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AdapterResult:
    """アダプタの送信結果。"""

    success: bool
    sent_count: int
    failed_readings: list = field(default_factory=list)
    error_message: Optional[str] = None


class AggregationAdapter(ABC):
    """先方サーバーへの送信境界を表す抽象基底クラス。"""

    @abstractmethod
    def send(self, readings: list) -> "AdapterResult":
        """Reading のリストを送信する。

        Args:
            readings: manager/record.py の Reading インスタンスのリスト。

        Returns:
            AdapterResult: 送信結果。失敗は例外ではなく
                success=False の AdapterResult で表現する。
        """
        raise NotImplementedError


class NullAdapter(AggregationAdapter):
    """何もしない参照実装。渡された readings 全件を成功扱いで返す。"""

    def send(self, readings: list) -> "AdapterResult":
        return AdapterResult(
            success=True,
            sent_count=len(readings),
            failed_readings=[],
            error_message=None,
        )
