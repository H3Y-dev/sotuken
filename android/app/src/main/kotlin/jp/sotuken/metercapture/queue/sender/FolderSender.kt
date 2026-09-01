package jp.sotuken.metercapture.queue.sender

import jp.sotuken.metercapture.queue.QueueItem

class FolderSender : Sender {
    override suspend fun send(item: QueueItem): Result<Unit> {
        // TODO(本人): 公開フォルダへ YYYYMMDDTHHMMSS_<localId>.jpg と同名の .json サイドカーを書き出す。Sprint 3
        TODO("公開フォルダへの書き出しはSprint 3で実装する")
    }
}

