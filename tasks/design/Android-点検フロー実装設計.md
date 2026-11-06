# Android 点検フロー 実装設計（P3〜P6）

作成: 2026-11-06。上位の決定: `tasks/design/点検フロー設計.md`（ユーザー決定・取り決め・PR分割）。画面の見本: `tasks/design/ui案/案B.html`（案Aの大きな撮影ボタンを入れる）。送信の基準: `tasks/design/送信機構レビュー結果.md`。機器IDとQR: `tasks/design/機器ID設計.md`、`tasks/design/QR機器ラベル仕様.md`。

この設計書だけを見て P3〜P6 を実装できるように書く。上位文書の取り決め（サイドカーのキー、`/routes`、manifest）はここで変えない。食い違いに気づいたら、上位文書を正とし、この設計書を直す。

**パスの省略**: `A/` = `android/app/src/main/kotlin/jp/sotuken/metercapture/`、`T/` = `android/app/src/test/kotlin/jp/sotuken/metercapture/`、`AT/` = `android/app/src/androidTest/kotlin/jp/sotuken/metercapture/`。行番号は main `c0958e1` 時点。

---

## 0. 現状のコードで確かめたこと（設計の前提）

| # | 事実 | 根拠 |
|---|---|---|
| F1 | `QueueItem` は Room の `queue_items` 表。追加列は既定値つきで末尾に足してきた（`sentVia`・`receiverId`・`deviceId`・`deviceIdSource`）。テストは位置引数10個で `QueueItem(...)` を作っている箇所がある | `A/queue/QueueItem.kt:6-28`、`T/queue/DeviceIdQueueTest.kt:33`、`T/queue/ReceiverPinTest.kt:55`、`T/queue/sender/HttpSenderTest.kt:262` |
| F2 | DBは version 4、`exportSchema = false`。移行は `ALTER TABLE ADD COLUMN` の積み重ね | `A/queue/CaptureDatabase.kt:12,18-35,37-40` |
| F3 | `QueueDao` を実装するのは `FakeQueueDao` だけ。`QueueDao` にメソッドを足すと、テスト側のFakeも直す必要がある | `A/queue/QueueDao.kt:11-33`、`T/queue/FakeQueueDao.kt:7` |
| F4 | `QueueStore` の実装は `RoomQueueStore` だけ。`enqueue(imageFile, meta: CaptureMeta)` が撮影の入口 | `A/queue/QueueStore.kt:22-37,77-98` |
| F5 | 送信は `QueueSendWorker` → `SendRouter.route()`。PENDINGを古い順に送り、PCに届かなければ送信箱（`FolderSender`）へ書いて `SENT`/`folder` にする。届くようになったら送信箱の分を追い送りする。送信全体は `queueSendMutex` で直列 | `A/queue/SendRouter.kt:27-130`、`A/queue/QueueSendWorker.kt:19-30`、`A/queue/QueueStore.kt:15` |
| F6 | `FAILED` は自動で再送しない（PENDINGだけを拾う）。FAILEDになるのは、HTTPの恒久エラー（400・413）か送信箱への書き込み失敗 | `A/queue/SendRouter.kt:56,74,86-94`、`A/queue/sender/HttpSender.kt:66-70` |
| F7 | 409（同名で内容が違う）は今 `TemporarySendException`。同じ内容の再送はPCが `200 {"duplicate":true}` を返す | `A/queue/sender/HttpSender.kt:66-70`、`manager/receiver.py:475-488` |
| F8 | Workerは実行のたびに `CaptureDatabase.create()` で別のDBインスタンスを開いて閉じる。画面側は `MainActivity` で別のインスタンスを持つ。Roomの変更通知はインスタンスをまたがない（`enableMultiInstanceInvalidation` を使っていない）ため、Workerが書いた送信状態が画面のFlowにすぐ届かない可能性がある（実機での確認は**未確認**） | `A/queue/QueueSendWorker.kt:33,74`、`A/MainActivity.kt:17` |
| F9 | 定期送信は15分ごとで、制約は `NetworkType.CONNECTED`。即時送信（`enqueueSend`）は制約なし、`APPEND_OR_REPLACE` | `A/queue/QueueSendScheduler.kt:17-38` |
| F10 | 画面は ViewModel を使っていない。`remember`・`rememberSaveable`・`collectAsStateWithLifecycle`・`rememberCoroutineScope` で状態を持つ。依存にも `lifecycle-viewmodel-compose` が無い。画面遷移も `showXxx` の真偽値とダイアログで切り替えている | `A/ui/MeterCaptureApp.kt:54-131,261-406`、`android/app/build.gradle.kts` の dependencies |
| F11 | 接続状況の帯は `connectionBarState`・`connectionBarText` の純粋関数と、`ConnectionBar`（文字列を受け取るだけ）に分かれている。疎通確認（ON_RESUME・15秒ごと・保存直後・撮影直後）は `MeterCaptureApp` の中に直接書いてある | `A/ui/ConnectionStatus.kt:12-82`、`A/ui/ConnectionBar.kt:28-44`、`A/ui/MeterCaptureApp.kt:79-136` |
| F12 | 表示用の純粋関数は `QueueDisplay.kt` に `internal fun` で置き、`T/ui/QueueDisplayTest.kt` で単体テストしている | `A/ui/QueueDisplay.kt:8-49` |
| F13 | サイドカーJSONは手組みの文字列。`device_id` は値があるときだけ載せる | `A/queue/sender/SenderPayloads.kt:27-42` |
| F14 | 機器QRの検証規則（ID `[A-Za-z0-9._-]{1,32}`、名前1〜64文字・制御文字なし）は `DeviceQr.kt` の private 定数と関数にある | `A/device/DeviceQr.kt:19-42,53-65` |
| F15 | `DeviceQrSection` はボタン・読み取りダイアログ・確認ダイアログを1つにまとめた部品で、`held = null` を渡せば保持中の表示を出さない | `A/ui/DeviceQrSection.kt:39-123` |
| F16 | 撮影ボタンは `CameraCapturePanel` の中の普通の `Button`（文言「撮影」） | `A/ui/CameraCapturePanel.kt:38-42,114-135` |
| F17 | 履歴画面のサムネイルと全画面表示は `QueueListScreen.kt` の private 関数 | `A/ui/QueueListScreen.kt:270-301,303-360` |
| F18 | PCは `0.0.0.0` で待ち受け、私用IPの接続元を許可する。サイドカーの `inspection_id` は `[A-Za-z0-9._-]{1,64}`、`inspection_name` は1〜64文字で、不正なら値を捨てて写真は受ける。`device_id_source` は `qr`・`manual` 以外を捨てる | `manager/receiver.py:696,771,134-144,183-185`、`manager/sidecar.py:54-65,106-108` |
| F19 | `ACCESS_NETWORK_STATE` 権限は既にある | `android/app/src/main/AndroidManifest.xml:13` |
| F20 | 既存のRoom移行テスト（androidTest）は `MIGRATION_1_2` だけを渡して開いている。DBが version 4 の今、この組み立てでは 2→4 の移行が足りず失敗するはず（実行して確かめてはいない。**未確認**） | `AT/queue/RoomQueueStoreInstrumentedTest.kt:44-46` |
| F21 | PC側の `/routes` と `/inspections/<id>/manifest` は、まだ `manager/receiver.py` に無い（P2で入る） | `manager/receiver.py` を grep して該当なし |

---

## 1. データモデル

### 1.1 新エンティティ `Inspection`（P3）

ファイル: `A/inspection/Inspection.kt`（新しいパッケージ `jp.sotuken.metercapture.inspection`）

```kotlin
@Entity(tableName = "inspections")
data class Inspection(
    @PrimaryKey val inspectionId: String,      // 例 "INS-20261106T003012Z-1a2b3c4d"。[A-Za-z0-9._-]{1,64}
    val name: String,                           // 点検名。前後空白を除いて1〜64文字、制御文字なし
    val operatorName: String?,                  // 担当者。空欄は null。1〜64文字
    val place: String?,                         // 場所。空欄は null。1〜64文字
    val routeId: String?,                       // ルートなしは null
    val routeName: String?,                     // 作成時のルート名（表示用）
    val routeSnapshot: String?,                 // 作成時にコピーしたルートJSON（§6.2の形）。ルートなしは null
    val state: InspectionState,
    val startedAt: String,                      // ISO-8601 UTC（Instant.toString()）
    val completedAt: String? = null,
    val completionSummary: String? = null,      // 完了時に計算した注意（§2.4のJSON）
    val manifestSentAt: String? = null,         // manifestが 200 で受け付けられた時刻
    val manifestError: String? = null,          // 直近のmanifest送信の失敗理由（成功で null）
    val pcMissingFileNames: String? = null,     // PC応答の missing_photos（JSON配列）。未送信は null
)

enum class InspectionState { IN_PROGRESS, WAITING, SENDING, SENT, SENT_INCOMPLETE }

class InspectionStateConverter {
    @TypeConverter fun from(value: InspectionState): String = value.name
    @TypeConverter fun to(value: String): InspectionState = InspectionState.valueOf(value)
}

data class RouteDevice(val id: String, val name: String)
```

- 担当者のプロパティ名を `operator` にしない（Kotlinの修飾子と同じ綴りで読みにくい）。manifestのキーは取り決めどおり `operator`。
- 外部キー（`queue_items.inspectionId → inspections`）は張らない。写真の行を消す処理は `QueueStore.delete` がファイルも含めて持っている（`A/queue/QueueStore.kt:44-75`）ので、CASCADEで行だけ消えるとファイルが残るため。
- 点検IDの作り方は §2.5。

### 1.2 `QueueItem` への追加（P3）

`A/queue/QueueItem.kt` の末尾に既定値つきで3列を足し、索引を付ける。

```kotlin
@Entity(tableName = "queue_items", indices = [Index(value = ["inspectionId"])])
data class QueueItem(
    ...既存のまま...,
    val deviceIdSource: String? = null,
    val inspectionId: String? = null,
    val inspectionName: String? = null,   // サイドカー用に作成時の点検名を写す（点検名は作成後に変えない）
    val routeId: String? = null,
)
```

- `inspectionName` を写真の行にも持つ理由: サイドカーは `SenderPayloads.buildSidecarJson(item)` が `QueueItem` だけから組み立てる（F13）。ここで点検表を引くと `Sender` の形を変えることになるため、名前を写しておく。点検名は作成後に変更できない仕様にする（§9）。
- 末尾に既定値つきで足すので、位置引数10個の既存テスト（F1）はそのまま通る。
- `CaptureMeta`（`A/queue/QueueItem.kt:39-45`）にも同じ3つを既定値 `null` で足し、`RoomQueueStore.enqueue`（`A/queue/QueueStore.kt:79-96`）で `QueueItem` へ写す。`QueueStore` のインターフェースは変えない。

### 1.3 Room version 4 → 5（P3）

`A/queue/CaptureDatabase.kt`:

```kotlin
@Database(entities = [QueueItem::class, Inspection::class], version = 5, exportSchema = false)
@TypeConverters(SendStateConverter::class, InspectionStateConverter::class)
abstract class CaptureDatabase : RoomDatabase() {
    abstract fun queueItemDao(): QueueDao
    abstract fun inspectionDao(): InspectionDao

    companion object {
        // 既存の MIGRATION_1_2〜3_4 はそのまま
        val MIGRATION_4_5: Migration = object : Migration(4, 5) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE queue_items ADD COLUMN inspectionId TEXT")
                db.execSQL("ALTER TABLE queue_items ADD COLUMN inspectionName TEXT")
                db.execSQL("ALTER TABLE queue_items ADD COLUMN routeId TEXT")
                db.execSQL("CREATE INDEX IF NOT EXISTS `index_queue_items_inspectionId` ON `queue_items` (`inspectionId`)")
                db.execSQL(
                    "CREATE TABLE IF NOT EXISTS `inspections` (" +
                        "`inspectionId` TEXT NOT NULL, `name` TEXT NOT NULL, `operatorName` TEXT, `place` TEXT, " +
                        "`routeId` TEXT, `routeName` TEXT, `routeSnapshot` TEXT, `state` TEXT NOT NULL, " +
                        "`startedAt` TEXT NOT NULL, `completedAt` TEXT, `completionSummary` TEXT, " +
                        "`manifestSentAt` TEXT, `manifestError` TEXT, `pcMissingFileNames` TEXT, " +
                        "PRIMARY KEY(`inspectionId`))",
                )
            }
        }

        val ALL_MIGRATIONS = arrayOf(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4, MIGRATION_4_5)

        @Volatile private var instance: CaptureDatabase? = null

        /** プロセスで1つだけ開く。Workerと画面が同じインスタンスを使い、変更通知を画面へ届ける（F8）。 */
        fun getInstance(context: Context): CaptureDatabase =
            instance ?: synchronized(this) {
                instance ?: create(context.applicationContext).also { instance = it }
            }

        fun create(context: Context): CaptureDatabase =
            Room.databaseBuilder(context, CaptureDatabase::class.java, "meter-capture.db")
                .addMigrations(*ALL_MIGRATIONS)
                .build()
    }
}
```

- CREATE文の列の型・NOT NULL・主キーは、§1.1 の Kotlin の型からRoomが期待する形にそろえてある（非nullの `String` と enum は `TEXT NOT NULL`、nullable は `TEXT`）。1文字でも違うとRoomの検証で起動時に落ちるので、§8 の移行テストで必ず確かめる。
- 索引名 `index_queue_items_inspectionId` はRoomの既定の命名規則どおり。
- **旧データ**: 既存の写真は3列とも NULL になる。`inspectionId = null` の写真は「点検に属さない写真」として、今までどおり送る（§3.1の判定で常に送信対象）。
- `fallbackToDestructiveMigration` は**使わない**（写真のキューが消える）。
- `MainActivity`（`A/MainActivity.kt:17`）と `QueueSendWorker`（`A/queue/QueueSendWorker.kt:33`）は `getInstance` に替え、Workerの `database.close()`（`:74`）を消す。

### 1.4 DAO（P3）

ファイル: `A/inspection/InspectionDao.kt`。`QueueDao` には足さない（F3。`FakeQueueDao` を変えずに済む）。写真の検索も、点検ごとのものはこのDAOに置く。

```kotlin
data class InspectionPhotoCount(
    val inspectionId: String,
    val photoCount: Int,
    val deviceCount: Int,
    val deliveredCount: Int,
)

@Dao
interface InspectionDao {
    @Insert(onConflict = OnConflictStrategy.ABORT) suspend fun insert(inspection: Inspection)
    @Update suspend fun update(inspection: Inspection)
    @Delete suspend fun delete(inspection: Inspection)

    @Query("SELECT * FROM inspections WHERE inspectionId = :id")
    suspend fun findById(id: String): Inspection?

    @Query("SELECT * FROM inspections WHERE inspectionId = :id")
    fun observeById(id: String): Flow<Inspection?>

    /** 点検の一覧（ホーム）。新しい順。 */
    @Query("SELECT * FROM inspections ORDER BY startedAt DESC")
    fun observeAll(): Flow<List<Inspection>>

    @Query("SELECT * FROM inspections WHERE state = :state ORDER BY startedAt ASC")
    suspend fun findByState(state: InspectionState): List<Inspection>

    @Query("SELECT name FROM inspections")
    suspend fun allNames(): List<String>

    @Query("UPDATE inspections SET state = :to WHERE state = :from")
    suspend fun resetState(from: InspectionState, to: InspectionState)

    /** 点検ごとの写真。撮影の古い順。 */
    @Query("SELECT * FROM queue_items WHERE inspectionId = :id ORDER BY capturedAt ASC")
    fun observePhotos(id: String): Flow<List<QueueItem>>

    @Query("SELECT * FROM queue_items WHERE inspectionId = :id ORDER BY capturedAt ASC")
    suspend fun findPhotos(id: String): List<QueueItem>

    /** ホームのカード用の集計。機器数は機器IDまたは機器名で数え、どちらも無い写真は数えない。 */
    @Query(
        "SELECT inspectionId, COUNT(*) AS photoCount, " +
            "COUNT(DISTINCT COALESCE(deviceId, 'name:' || deviceName)) AS deviceCount, " +
            "SUM(CASE WHEN sendState = 'SENT' AND sentVia = 'http' THEN 1 ELSE 0 END) AS deliveredCount " +
            "FROM queue_items WHERE inspectionId IS NOT NULL GROUP BY inspectionId",
    )
    fun observePhotoCounts(): Flow<List<InspectionPhotoCount>>

    /** PCの missing_photos に入った「届いたはずの写真」を送り直しへ戻す（P6）。 */
    @Query(
        "UPDATE queue_items SET sendState = 'PENDING', lastError = NULL " +
            "WHERE inspectionId = :id AND localId IN (:localIds) AND sendState = 'SENT'",
    )
    suspend fun requeueSent(id: String, localIds: List<String>): Int
}
```

- **集計の基準はKotlinの純粋関数 `summarizeInspection`（§2.4）**。未撮影・追加はルートのJSONとの照合が要るため、SQLでは出さない。SQLの `observePhotoCounts` はホームの枚数・機器数だけに使い、同じ写真で `summarizeInspection` と同じ数になることをテストで確かめる（§8）。
- `'name:' || deviceName` は deviceName が NULL なら NULL になり、`COUNT(DISTINCT ...)` は NULL を数えない。機器名のみの写真は名前で1機器と数える（機器ID設計 5章「旧データは `name:<device_name>` で束ねる」に合わせる）。
- `requeueSent` は P6 で使う。P3 で書いておくとRoomの生成コードの差分が1回で済むが、使わない関数を先に入れない方針に合わせ、**P6で追加する**。上のリストは最終形。

---

## 2. 点検の状態機械

### 2.1 状態と画面の文言

| 状態 | 画面の文言 | 意味 |
|---|---|---|
| `IN_PROGRESS` | 作業中 | 撮影・削除ができる。写真は送らない |
| `WAITING` | 送信待ち | 完了済み。写真またはmanifestがまだPCに届いていない |
| `SENDING` | 送信中 | Workerがこの点検を処理している最中（PCに届くと確かめた後だけ） |
| `SENT` | 送信済み | 写真がすべてHTTPで届き、manifestが 200 で受け付けられ、PCの `missing_photos` が空 |
| `SENT_INCOMPLETE` | 送信済み（未到着N枚） | manifestは届いたが、届いていない写真がある（端末で `FAILED`、またはPCの `missing_photos` に載った） |

N = `FAILED` の写真の数 ＋ `pcMissingFileNames` の数（同じファイル名は1回）。

### 2.2 遷移

```
           complete()            beforeRoute(PCに届く)
IN_PROGRESS ─────────▶ WAITING ─────────────────────▶ SENDING
                         ▲  ▲                           │
                         │  └──── afterRoute: 未送信が残る / manifest失敗 / 中断の復旧
                         │                              │
       retryUndelivered()│        afterRoute: manifest 200 かつ未到着0 ──▶ SENT
                         │                              │
                         └──── SENT_INCOMPLETE ◀────────┘ afterRoute: manifest 200 かつ未到着あり
```

| 遷移 | 契機（呼ぶ関数） | 条件 |
|---|---|---|
| (作成) → IN_PROGRESS | `InspectionStore.create` | — |
| IN_PROGRESS → WAITING | `InspectionStore.complete`（完了確認の「点検を完了する」） | 写真が1枚以上 |
| WAITING → SENDING | `InspectionSendCoordinator.beforeRoute(reachable = true)` | PCの疎通確認が成功した回だけ |
| SENDING → WAITING | `afterRoute` | 未送信の写真が残る（PENDING・SENDING・送信箱止まり・別PC宛て保留）、manifest送信の失敗、送信先なし |
| SENDING → WAITING | `beforeRoute` の最初（中断の復旧） | 前回の処理中にアプリが終了した |
| SENDING → SENT | `afterRoute` | 下の「manifestを送る条件」を満たし、200、未到着0 |
| SENDING → SENT_INCOMPLETE | `afterRoute` | 同上で 200、未到着1以上 |
| SENT_INCOMPLETE → WAITING | `InspectionStore.retryUndelivered`（「届いていない写真を再送」） | — |

**禁止する遷移**（`IllegalStateException`。DBは変えない）: どの状態からも IN_PROGRESS へは戻らない（完了後の再開は不可、§9）。IN_PROGRESS から SENDING・SENT・SENT_INCOMPLETE へ直接は行かない。SENT からはどこへも行かない（削除だけ、§2.6）。WAITING → SENT（SENDINGを経ずに）は無い。

遷移の判定は純粋関数に置き、ストアとコーディネーターはこれを通してから書く。

```kotlin
// A/inspection/InspectionStateMachine.kt
sealed interface InspectionEvent {
    data object Complete : InspectionEvent
    data object StartSending : InspectionEvent
    data object Recover : InspectionEvent
    data object RoundUnfinished : InspectionEvent
    data class ManifestAccepted(val undeliveredCount: Int) : InspectionEvent
    data object RetryUndelivered : InspectionEvent
}

/** 許されない遷移は IllegalStateException。 */
fun nextInspectionState(current: InspectionState, event: InspectionEvent): InspectionState
```

### 2.3 送信の対象

- 写真の `inspectionId == null` → 今までどおり送る。
- 写真の `inspectionId != null` → その点検が `WAITING` か `SENDING` のときだけ送る（送信箱への書き出しと追い送りも同じ。作業中の写真は送信箱にも書かない。USB吸い出しで完了前の写真がPCへ渡らないようにするため）。
- 点検の行が見つからない写真（通常は起きない。§2.6の削除は写真を先に消す）→ 送る。写真を失わないことを優先する。

判定関数（P3、`A/inspection/InspectionSendRules.kt`）:

```kotlin
val SENDABLE_INSPECTION_STATES = setOf(InspectionState.WAITING, InspectionState.SENDING)

fun isPhotoSendable(item: QueueItem, inspectionState: InspectionState?): Boolean =
    item.inspectionId == null || inspectionState == null || inspectionState in SENDABLE_INSPECTION_STATES
```

### 2.4 完了時の集計（未撮影・重複・追加）

ファイル: `A/inspection/InspectionSummary.kt`（純粋関数）

```kotlin
data class DuplicateDevice(val deviceId: String?, val deviceName: String?, val count: Int)

data class InspectionSummary(
    val photoCount: Int,
    val deviceCount: Int,                 // 機器ID、無ければ機器名で数えた異なる機器の数
    val routeDeviceCount: Int?,           // ルートなしは null
    val shotRouteDeviceCount: Int?,       // ルートの機器のうち1枚以上撮った数。ルートなしは null
    val missing: List<RouteDevice>,       // ルートの順。ルートなしは空
    val duplicates: List<DuplicateDevice>,// 2枚以上の機器。最初に撮った順
    val extra: List<String>,              // ルートに無い機器ID。最初に撮った順。ルートなしは空
    val unidentifiedCount: Int,           // 機器IDの無い写真の数
)

fun summarizeInspection(photos: List<QueueItem>, routeDevices: List<RouteDevice>?): InspectionSummary
fun InspectionSummary.toJson(): String           // completionSummary 列に保存
fun parseInspectionSummary(json: String): InspectionSummary?
```

- 機器のキー: `deviceId` があればそれ、無ければ `"name:" + deviceName.trim()`、どちらも無ければキーなし（`deviceCount` と `duplicates` に入らない）。
- 未撮影: ルートの機器のうち、同じ `deviceId` の写真が無いもの。機器名だけの一致は数えない（取り決めのIDで照合する）。
- 追加（extra）: ルートがあるときだけ。写真の `deviceId` のうちルートに無いもの。
- `completionSummary` には `{"v":1,"missing":[{"id","name"}],"extra":["Z-9"],"duplicates":[{"id","name","count"}],"unidentified":N}` を保存する。件数系（`photoCount` など）は写真から毎回出せるので保存しない。完了後は写真が変わらない（撮影・削除を止める）ので、保存した注意と写真から出した数は食い違わない。
- 完了確認の画面は、完了する**前**に同じ関数で計算して見せる。完了時にもう一度計算して保存する（確認から完了までの間に写真が変わっても、保存されるのは完了時点の値）。

### 2.5 点検IDと点検名

ファイル: `A/inspection/InspectionNaming.kt`

```kotlin
/** "INS-" + UTCの yyyyMMdd'T'HHmmss'Z' + "-" + 乱数8桁の16進。29文字。 */
fun newInspectionId(now: Instant, random: () -> String = { UUID.randomUUID().toString().take(8) }): String

/** "MM/dd 朝の点検"。同じ名前があれば " 2"、" 3" … を付ける。 */
fun defaultInspectionName(now: ZonedDateTime, existingNames: Collection<String>): String

/** 時間帯: 4:00〜10:59 朝、11:00〜14:59 昼、15:00〜18:59 夕方、それ以外 夜。日付は開始時の端末の日付。 */
fun timeSlotLabel(hour: Int): String

/** 入力欄の検証。前後空白を除き、空なら null、1〜64文字で制御文字なしなら値、それ以外は例外。 */
fun normalizeInspectionText(raw: String): String?

val INSPECTION_ID_PATTERN = Regex("[A-Za-z0-9._-]{1,64}")
```

- 点検IDに乱数を入れるのは、複数のスマホが同じ秒に点検を作ってもPCで混ざらないようにするため。
- 点検名が空欄なら `defaultInspectionName` を使う。入力された名前が既存と重なっても、そのまま許す（IDで区別するため）。

### 2.6 永続化と削除

- 状態はすべて `inspections.state` に保存する。SENDINGも保存し、Workerの開始時（`beforeRoute`）に SENDING → WAITING へ戻す（写真の `recoverInterruptedSends` と同じ考え方。`A/queue/QueueStore.kt:162-164`）。
- 点検の削除は **IN_PROGRESS のときだけ**。写真を `QueueStore.delete` で1枚ずつ消し（ファイルも消える）、最後に点検の行を消す。作業中の写真は送信対象外なので SENDING になっておらず、`DeleteResult.SENDING` は返らない。返った場合は途中でやめ、点検の行を残す。
- 送信済みの点検の端末からの片付けは初版では作らない（`送信機構レビュー結果.md` P1「原本の削除は保持期間・手動削除を別に設ける」に合わせる）。

### 2.7 `InspectionStore`（P3で作り、P4・P6で関数を足す）

ファイル: `A/inspection/InspectionStore.kt`

```kotlin
data class NewInspection(
    val name: String,              // 空欄なら defaultInspectionName
    val operatorName: String,
    val place: String,
    val route: RouteDoc? = null,   // P5で選べるようになる。P3では常に null
)

data class InspectionListItem(val inspection: Inspection, val counts: InspectionPhotoCount?)

interface InspectionStore {
    fun observeInspections(): Flow<List<InspectionListItem>>                 // P3
    fun observeInspection(id: String): Flow<Inspection?>                    // P3
    fun observePhotos(id: String): Flow<List<QueueItem>>                    // P3
    suspend fun create(input: NewInspection, now: Instant = Instant.now()): Inspection          // P3
    suspend fun addPhoto(inspectionId: String, imageFile: File, meta: CaptureMeta): String       // P3（P4の画面から使う）
    suspend fun complete(inspectionId: String, now: Instant = Instant.now()): InspectionSummary // P3
    suspend fun delete(inspectionId: String): Boolean                                           // P3
    suspend fun deletePhoto(inspectionId: String, localId: String): DeleteResult                // P4
    suspend fun retryUndelivered(inspectionId: String)                                           // P6
}

class RoomInspectionStore(
    private val inspectionDao: InspectionDao,
    private val queueStore: QueueStore,
    private val runInTransaction: suspend (suspend () -> Unit) -> Unit,
    private val zone: ZoneId = ZoneId.systemDefault(),
) : InspectionStore
```

- `runInTransaction` は本番で `{ block -> database.withTransaction { block() } }`（room-ktx。依存は既にある）、テストで `{ it() }`。
- `addPhoto`: 点検が IN_PROGRESS でなければ `IllegalStateException`。`meta` の `inspectionId`・`inspectionName`・`routeId` を点検の値で上書きしてから `queueStore.enqueue` を呼ぶ。
- `complete`: `queueSendMutex.withLock` の中で、トランザクションで「写真を読む → 0枚なら例外 → `summarizeInspection` → `nextInspectionState(..., Complete)` → `state`・`completedAt`・`completionSummary` を更新」。呼び出し側（画面）が成功後に `QueueSendScheduler.enqueueSend` を呼ぶ。
- `deletePhoto`: IN_PROGRESS でなければ例外。写真の `inspectionId` が違えば `DeleteResult.NOT_FOUND`。あとは `queueStore.delete`。

---

## 3. 送信の組み立て

### 3.1 既存の送信との接続

**P3**: `SendRouter` の引数の末尾に既定値つきで判定を足す（既存の呼び出し元 `QueueSendWorker.kt:62-69` と `T/queue/SendRouterTest.kt` は変えずに通る）。

```kotlin
class SendRouter(
    ...既存の引数...,
    private val currentReceiverId: String? = null,
    private val isSendable: suspend (QueueItem) -> Boolean = { true },
)
```

- PENDINGのループ（`SendRouter.kt:58-59`）で `if (item.isHeldFor(currentReceiverId)) continue` の次に `if (!isSendable(item)) continue`。
- 追い送りの対象（`SendRouter.kt:47-53`）の filter にも `isSendable(it)` を足す（suspend なので `filter` ではなく for で組む）。
- Workerは `isSendable = { item -> isPhotoSendable(item, item.inspectionId?.let { inspectionDao.findById(it)?.state }) }` を渡す。

**P6**: Workerの流れを次にする（`A/queue/QueueSendWorker.kt:32-76` を置き換え）。

```
db = CaptureDatabase.getInstance(ctx)
target = ReceiverSettings(ctx).sendTarget()
reach = pickReachableUrl(target.candidateUrls) { url -> HttpSender.health(url, target.token!!) }   // §4.3
coordinator = InspectionSendCoordinator(
    inspectionDao,
    manifestPoster = reach.url?.let { url -> { id, json -> HttpSender(url, target.token!!).postManifest(id, json) } },
    sha256Of = { item -> runCatching { SenderPayloads.computeSha256Hex(File(item.imagePath)) }.getOrNull() },
    now = { Instant.now() },
)
coordinator.beforeRoute(reachable = reach.url != null)
SendRouter(queueDao, queueStore, outboxDir,
    httpSenderProvider = { reach.url?.let { HttpSender(it, target.token!!) } },
    healthChecker = { if (reach.url != null) Result.success(Unit) else Result.failure(reach.error ?: IllegalStateException("送信先未設定")) },
    currentReceiverId = target.receiverId,
    isSendable = coordinator::isSendable,
).route()
coordinator.afterRoute(currentReceiverId = target.receiverId)
```

- 疎通確認はWorkerで1回だけ行い、その結果を `SendRouter` の `healthChecker` に渡す（同じGETを2回送らない）。
- 送信先が未設定なら `httpSenderProvider` が null を返す。`SendRouter` の既存の動き（送信箱へ書く）のまま。

### 3.2 サイドカー（P3）

`A/queue/sender/SenderPayloads.kt:27-42` の `buildSidecarJson` の末尾（`}` の前）に足す。

```kotlin
if (item.inspectionId != null) {
    append(",\"inspection_id\":").append(jsonString(item.inspectionId))
    item.inspectionName?.let { append(",\"inspection_name\":").append(jsonString(it)) }
    item.routeId?.let { append(",\"route_id\":").append(jsonString(it)) }
}
```

- `inspectionId` が null の写真の出力は1文字も変わらない（既存の `ReceiverPinTest.kt:162`、`DeviceIdSidecarTest.kt:33,45` の期待値はそのまま）。
- 34行目のコメント「手入力は付けない」は、P4で手入力の機器ID（`manual`）を付けるようになるので「機器IDがあるときだけ載せる（出所は qr または manual）」に直す。

### 3.3 manifest の組み立て（P6）

ファイル: `A/inspection/InspectionManifest.kt`（純粋関数。`kotlinx.serialization.json.buildJsonObject` を使う。既に `A/pairing/PairingClient.kt:29` で使っている）

```kotlin
fun buildManifestJson(
    inspection: Inspection,
    photos: List<QueueItem>,                 // 撮影の古い順
    summary: InspectionSummary,              // completionSummary を読んだもの
    sha256Of: (QueueItem) -> String?,
): String
```

出力（取り決めどおり。キーは常に出す）:

```json
{"v":1,"inspection_id":"INS-...","inspection_name":"11/06 朝の点検","route_id":"R-1",
 "operator":"大久保","place":"第1工場","started_at":"2026-11-06T00:30:12Z","completed_at":"2026-11-06T00:52:40Z",
 "photos":[{"file_name":"20261106T003301_<localId>.jpg","sha256":"<64桁>","device_id":"A-101","device_id_source":"qr","captured_at":"2026-11-06T00:33:01.120Z"}],
 "missing":["A-103"],"extra":["Z-9"]}
```

- `file_name` は `SenderPayloads.buildImageFileName(item)`（`SenderPayloads.kt:20-25`）。写真の送信と同じ名前。
- `sha256` は元画像ファイルのSHA-256（`SenderPayloads.computeSha256Hex(file)`、`:54-64`）。ファイルが無ければ `null` にし、PCでは未着として扱われる。
- `route_id`・`operator`・`place`・`device_id`・`device_id_source` は値が無ければ `null`。ルートなしの点検は `"missing":[]`・`"extra":[]`（PCは `route_id` が null なら未撮影を判定しない。P2側へ伝える事項、§11）。
- `photos` には `FAILED` の写真も入れる（PCの `missing_photos` に出て、PC側でも未着と分かる）。

### 3.4 manifest の送信（P6）

`A/queue/sender/HttpSender.kt` に足す（`buildUrl`・`readResponseText` を共用するため新ファイルにしない）。

```kotlin
data class ManifestReply(val matched: Int, val missingPhotos: List<String>)

suspend fun postManifest(inspectionId: String, json: String): Result<ManifestReply>
```

- `POST {baseUrl}/inspections/{inspectionId}/manifest`。`inspectionId` は `INSPECTION_ID_PATTERN` で検証してからパスに入れる（不一致は `PermanentSendException`）。
- ヘッダー: `X-Sotuken-Token`、`Content-Type: application/json; charset=utf-8`。`instanceFollowRedirects = false`、`setFixedLengthStreamingMode`。タイムアウトは送信と同じ既定値。
- 応答: 200 で本文（64KiBまで読む）を `parseManifestReply` で読む。`ok` が `true` でない・形が違う → `TemporarySendException`。400・413 → `PermanentSendException`。404 → `TemporarySendException("PCが点検の一覧の受信に未対応です。PCのアプリを更新してください")`（P2が入る前のPC）。それ以外 → `TemporarySendException`。
- `parseManifestReply(text: String): ManifestReply?` は純粋関数として `A/inspection/InspectionManifest.kt` に置く。

**409 の扱いの変更（P6）**: `HttpSender.send` の分類（`HttpSender.kt:66`）を `responseCode == 400 || responseCode == 409 || responseCode == 413` に変える。同名で中身が違う写真は何度送っても通らず（F7）、今は一時エラー扱いで送信箱への書き込みと追い送りを繰り返すため。既存の `uploadClassifiesHttpResponses`（`T/queue/sender/HttpSenderTest.kt:259`）は409を含まないので、期待値は変わらない。

### 3.5 送信後の判定 `InspectionSendCoordinator`（P6）

ファイル: `A/inspection/InspectionSendCoordinator.kt`

```kotlin
class InspectionSendCoordinator(
    private val inspectionDao: InspectionDao,
    private val manifestPoster: (suspend (String, String) -> Result<ManifestReply>)?,
    private val sha256Of: (QueueItem) -> String?,
    private val now: () -> Instant,
) {
    suspend fun beforeRoute(reachable: Boolean)          // SENDING→WAITING（復旧）、reachable なら WAITING→SENDING
    suspend fun isSendable(item: QueueItem): Boolean     // §2.3
    suspend fun afterRoute(currentReceiverId: String?)   // SENDINGの点検ごとに判定
}

sealed interface RoundOutcome {
    data object Unfinished : RoundOutcome
    data class ReadyForManifest(val failedFileNames: List<String>) : RoundOutcome
}

/** 純粋関数。afterRoute の判定の中身。 */
fun decideAfterRound(photos: List<QueueItem>, currentReceiverId: String?): RoundOutcome
```

`decideAfterRound` の規則:
- 写真のどれかが `PENDING`・`SENDING`、または `SENT` かつ `sentVia == folder`（送信箱止まり）、または `isHeldFor(currentReceiverId)` → `Unfinished`。
- それ以外（すべてが `SENT`/`http` か `FAILED`）→ `ReadyForManifest(FAILEDの写真の file_name)`。

`afterRoute` の流れ（点検ごと）:
1. `Unfinished` → WAITING。`manifestError` は変えない。
2. `ReadyForManifest` で `manifestPoster == null` → WAITING、`manifestError = "PCに届かないため、写真の一覧を送れませんでした"`。
3. `ReadyForManifest` で送信 → 成功: `undelivered = failedFileNames ∪ reply.missingPhotos`。0なら SENT、1以上なら SENT_INCOMPLETE。`manifestSentAt = now`、`manifestError = null`、`pcMissingFileNames = reply.missingPhotos のJSON`。失敗: WAITING、`manifestError = 理由（classifyFailureMessage と同じ短い文言）`。

`afterRoute` は `queueSendMutex` の中（Worker の `doWork` 全体がロック内、`QueueSendWorker.kt:21`）で動くので、画面からの `complete`・`retryUndelivered` と同時に書き込まない（両方とも同じMutexを取る）。

### 3.6 一部失敗の再送と冪等性

| 場面 | 画面の操作 | 処理 |
|---|---|---|
| 写真が端末で `FAILED` | 「届いていない写真を再送」 | `retryUndelivered`: Mutex内・トランザクションで、FAILEDの写真を `queueStore.retry`（PENDINGへ）、`pcMissingFileNames` に載った `SENT` の写真を `requeueSent` でPENDINGへ、点検を `RetryUndelivered` で WAITING、`manifestError = null`。その後 `enqueueSend` |
| PCの `missing_photos` に載った | 同上 | 同上。PCは同名・同内容の写真に `200 duplicate` を返す（F7）ので、二重には保存されない |
| manifestだけ失敗（WAITINGで写真はすべて到着） | 「写真の一覧だけ再送」 | `enqueueSend` だけ。次の回で `beforeRoute` が SENDING にし、`afterRoute` がmanifestを送り直す。写真は送らない（すべて `SENT`/`http` なので対象にならない） |
| manifestの二重送信 | — | PCは同じ点検IDのmanifestを上書きする（取り決め）。応答が失われて再送しても結果は同じ |
| 写真のアップロード成功後に応答が失われた | — | 既存の動き: IOException → 送信箱 → 次の回で追い送り → `200 duplicate`。manifestは追い送りが終わってから送る |
| 同名で内容が違う（409） | 「届いていない写真を再送」で再試行は可能 | P6から `FAILED`（恒久）。点検は SENT_INCOMPLETE になる |

自動の再試行: `FAILED` は自動では戻さない（既存方針、`送信機構レビュー結果.md` P1「無限自動再試行は足さない」）。一時的な失敗は送信箱経由で、§4.4 のきっかけのたびに追い送りされる。

---

## 4. 接続の判定と自動送信のきっかけ

### 4.1 「PCに届く」

既存の疎通確認 `HttpSender.health(url, token)`（`HttpSender.kt:90-118`。`GET /health`、接続2秒・読み取り3秒）が成功したら「PCに届く」。変えない。

### 4.2 接続の種類

ファイル: `A/ui/NetworkStatus.kt`（P6）

```kotlin
data class NetworkSnapshot(val wifi: Boolean, val wired: Boolean, val usbTether: Boolean)

/** 純粋関数。表示の文言。 */
fun networkLabel(snapshot: NetworkSnapshot): String
//  wifi && usbTether → "Wi-Fi＋USBテザリング"、wifi → "Wi-Fi"、usbTether → "USBテザリング"、wired → "有線LAN"、どれも無い → "未接続"

/** 純粋関数。USBテザリングの網の名前か。 */
fun isUsbTetherInterfaceName(name: String): Boolean = Regex("^(rndis|usb|ncm)\\d+$").matches(name)

/** 端末から読む（純粋でない）。IOで呼ぶ。 */
fun readNetworkSnapshot(context: Context): NetworkSnapshot
```

`readNetworkSnapshot` の中身:
- Wi-Fi・有線: `ConnectivityManager.allNetworks` を使わず、`registerNetworkCallback` で受け取った `Network` の `NetworkCapabilities` を見る。`TRANSPORT_WIFI` → wifi、`TRANSPORT_ETHERNET` または `TRANSPORT_USB`（API 31以上）→ wired。モバイル通信だけ（`TRANSPORT_CELLULAR`）は、PCの私用IPへは届かないので「未接続」と同じ扱いにする。
- USBテザリング: スマホがテザリングの親になっているときは、その網がアプリの `Network` として見えない。`java.net.NetworkInterface.getNetworkInterfaces()` で、`isUp` かつループバックでなく、名前が `isUsbTetherInterfaceName` に合い、IPv4アドレスを持つものがあれば true。
- 網の名前（`rndis0`・`usb0`・`ncm0`）は機種で違う。対象端末での実際の名前は**未確認**（§10、実機確認の項目）。

画面での監視: `rememberReceiverHealth`（§5.3）の中で、`DisposableEffect` で `ConnectivityManager.registerNetworkCallback(NetworkRequest.Builder().build(), callback)` を登録し、`onAvailable`・`onLost`・`onCapabilitiesChanged` で `readNetworkSnapshot` を取り直して疎通確認もやり直す。USBテザリングの切り替えはこのコールバックでは来ないので、既存の15秒ごとの確認（`MeterCaptureApp.kt:124-131`）と ON_RESUME でも取り直す。

### 4.3 USBテザリングで送るときの送信先URL

USBテザリング中、PCのアドレスはスマホが配る別の網のもの（Wi-Fiで登録したURLとは違う）になる。Wi-Fiで登録したURLのままでは、Wi-Fiが無い場所でテザリングしても届かない。

設計（P6）:
- `ReceiverSettings` に「同じPCの別のURL」を最大3件持つ（`KEY_ALT_URLS`、JSON配列の文字列）。
- `savePaired`（`A/settings/ReceiverSettings.kt:36-47`）: 保存済みの `receiverId` と同じPCを登録し直し、URLが違うときは、今のURLを候補の先頭へ移してから新しいURLを主にする（重複は除き、3件を超えたら古いものを捨てる）。違うPCなら候補を消す。
- `save(url, token)`（手入力、`:49-69`）: 候補を消す（`receiverId` を消す既存の動きに合わせる）。
- `SendTarget` に `candidateUrls: List<String>`（主URL＋候補）を足す。`isConfigured()` は今のまま主URLで判定する。
- 疎通確認は候補を順に試し、最初に届いたURLで送る。

```kotlin
// A/settings/ReceiverUrlCandidates.kt（純粋関数）
fun mergeCandidateUrls(currentUrl: String?, currentAlts: List<String>, newUrl: String, sameReceiver: Boolean): List<String>

data class Reachability(val url: String?, val error: Throwable?)
suspend fun pickReachableUrl(candidates: List<String>, health: suspend (String) -> Result<Unit>): Reachability
```

作業者の操作は「テザリングをオンにして、PCの『スマホを登録』のQRを一度読む」。2回目からは自動で切り替わる。テザリングのたびにPCのアドレスが変わる機種なら毎回の登録が要る（**未確認**。§10と要確認2）。

既存テストへの影響: `PairedSettingsTest.kt:34-65` の3件は、新しい鍵を1つ足すだけで、`apply` の回数・主URL・トークン・`receiverId`・PC名の期待値は変わらない。

### 4.4 自動送信のきっかけ

| きっかけ | 実装 | 備考 |
|---|---|---|
| 点検の完了 | 完了確認の画面が `complete` 成功後に `QueueSendScheduler.enqueueSend` | P4 |
| アプリの起動 | 既存（`MainActivity.kt:24-25`） | 変えない |
| 15分ごとの定期実行 | 既存（`QueueSendScheduler.kt:26-38`） | USBテザリングだけの状態では `NetworkType.CONNECTED` を満たさず動かない見込み（**未確認**）。そのため下の「PCに届くようになった」をアプリ表示中のきっかけにする |
| PCに届くようになった | `rememberReceiverHealth` が、疎通確認の結果が「届かない／未確認」から「届く」に変わったとき、送るものがあれば `enqueueSend` | P6。判定は純粋関数 `shouldTriggerAutoSend(previous: Boolean?, now: Boolean, hasWork: Boolean) = now && previous != true && hasWork`。`hasWork` = WAITINGの点検があるか、点検に属さない未着の写真がある |
| 接続の変化 | §4.2 のコールバック → 疎通確認 → 上の行 | P6 |
| 今すぐ送る | 送信待ちの画面のボタン、既存の履歴画面のボタン（`QueueListScreen.kt:127-129`） | — |

### 4.5 既存の接続状況の帯との統合

- 帯の文言は、既存の `connectionBarText`（`ConnectionStatus.kt:72-82`）の前に接続の種類を付けた `"${networkLabel(snapshot)}　${connectionBarText(...)}"` にする。既存の関数と `ConnectionStatusTest` の期待値は変えない。結合は新関数 `connectionBarTextWithNetwork(snapshot, state, undelivered, lastSent, reason)` として `NetworkStatus.kt` に置く。
- 帯の「未着 N件」は、送信対象の写真だけで数える: `countUndelivered(items.filter { isPhotoSendable(it, stateOf(it)) })`。作業中の点検の写真を「未着」に数えない。`countUndelivered` 自体は変えない。
- `ConnectionBar`（`ConnectionBar.kt:28-44`）は文字列を受け取るだけなので変えない。

---

## 5. 画面と遷移

### 5.1 方針

- **ViewModelは使わない**。既存と同じく `remember`／`rememberSaveable`＋Flowの `collectAsStateWithLifecycle`＋`rememberCoroutineScope` で書く（F10）。依存を増やさない。ストア（`QueueStore`・`InspectionStore`）は `MainActivity` で作って引数で渡す。
- 画面に出す文言・件数・ボタンの出し分けは、画面ごとの `XxxUiState`（data class）を作る純粋関数に切り出し、JVMの単体テストで確かめる（`QueueDisplay.kt` と同じ流儀）。Composableは `XxxUiState` を描くだけにする。
- 遷移はナビゲーションのライブラリを入れず、文字列の戻り先スタック（`rememberSaveable`）と `when` で切り替える。戻るボタンは `androidx.activity.compose.BackHandler`（activity-compose に含まれる）。
- 新しい画面はすべて `A/ui/inspection/` の新ファイルに置く。`MeterCaptureApp.kt`・`QueueListScreen.kt` の変更は §7 に書いた最小限だけ。

### 5.2 遷移

```kotlin
// A/ui/inspection/AppScreen.kt
sealed interface AppScreen {
    data object Home : AppScreen
    data object Create : AppScreen
    data class Capture(val inspectionId: String) : AppScreen
    data class History(val inspectionId: String) : AppScreen
    data class Complete(val inspectionId: String) : AppScreen
    data class SendStatus(val inspectionId: String) : AppScreen
    data object ConnectionGuide : AppScreen
    data object Routes : AppScreen          // P5
    data object LegacyCapture : AppScreen   // 既存の撮影画面（点検なし）
}

fun AppScreen.encode(): String            // "home"、"capture/INS-..." など。IDは [A-Za-z0-9._-] なので "/" で区切れる
fun decodeAppScreen(text: String): AppScreen   // 読めなければ Home

/** 点検の状態に合わない画面を直す。点検が無ければ Home。作業中でないのに Capture・Complete・History なら SendStatus。 */
fun resolveScreen(requested: AppScreen, state: InspectionState?): AppScreen
```

| 画面 | 入口 | 主な移動先 |
|---|---|---|
| Home（点検の一覧） | 起動時 | 新しい点検を作る→Create、作業中のカード「点検を続ける」→Capture、送信待ち・送信中「状態を見る」→SendStatus、送信済み「送信結果を見る」→SendStatus、下部「接続を確認する」→ConnectionGuide、「送信先の設定」→設定ダイアログ、「ルート」（P5）→Routes、「点検なしで撮る（従来の画面）」→LegacyCapture |
| Create | Home | 点検を始める→Capture（スタックは Home, Capture） |
| Capture | Create、Home、History | 履歴→History、点検完了へ→Complete、点検一覧→Home |
| History | Capture | 撮影へ戻る→Capture（撮り直し・この機器を撮るは対象を渡して）、点検完了へ→Complete |
| Complete | Capture、History | 確認して完了→SendStatus（スタックは Home, SendStatus）、履歴に戻る→History |
| SendStatus | Complete、Home | 接続の案内→ConnectionGuide、点検の一覧へ→Home |
| ConnectionGuide | Home、SendStatus | 点検の一覧へ→Home、送信先の設定を見る→設定ダイアログ |
| LegacyCapture | Home | 戻る→Home |

撮影対象を Capture へ渡すとき（撮り直し・この機器を撮る）は、AppScreen に名前を入れず、`InspectionApp` が持つ `pendingTarget`（`rememberSaveable` で id・name・source の3つの文字列）に置き、Capture が最初の描画で受け取って空にする。

### 5.3 共通部品

| ファイル | 中身 |
|---|---|
| `A/ui/inspection/InspectionApp.kt` | `@Composable fun InspectionApp(queueStore: QueueStore, inspectionStore: InspectionStore, routeRepository: RouteRepository? = null)`。スタック、`BackHandler`、`resolveScreen`、設定ダイアログ・状態ダイアログの表示を持つ。`MainActivity` の `setContent` はこれを呼ぶ |
| `A/ui/inspection/InspectionScaffold.kt` | `@Composable fun InspectionScaffold(title: String, health: ReceiverHealthState, barUndelivered: Int, onBarClick: () -> Unit, onHome: (() -> Unit)?, content: @Composable ColumnScope.() -> Unit)`。上から ConnectionBar、題名と「点検一覧」、本文 |
| `A/ui/ReceiverHealth.kt` | `MeterCaptureApp.kt:79-131` の疎通確認を移した状態ホルダー。下に定義 |
| `A/ui/ReceiverSettingsDialog.kt` | `MeterCaptureApp.kt:309-386` の設定ダイアログを中身を変えずに移したもの。`@Composable internal fun ReceiverSettingsDialog(receiverSettings: ReceiverSettings, onDismiss: () -> Unit, onSaved: () -> Unit, onOpenPairing: () -> Unit)` |
| `A/ui/inspection/LegacyQueueView.kt` | `class LegacyQueueView(private val inner: QueueStore) : QueueStore by inner { override fun observeQueue() = inner.observeQueue().map { it.filter { item -> item.inspectionId == null } } }`。従来の画面には点検に属さない写真だけを見せる（従来の履歴から点検の写真を消したり再送したりさせない） |

```kotlin
// A/ui/ReceiverHealth.kt
@Stable
class ReceiverHealthState internal constructor(...) {
    val configured: Boolean
    val healthOk: Boolean?
    val reason: String
    val network: NetworkSnapshot          // P6で追加。P3では常に NetworkSnapshot(false, false, false) で表示に使わない
    fun check(force: Boolean = false)
    fun onSettingsChanged()               // settingsVersion を進め、healthOk を null にして force で確認
}

@Composable
fun rememberReceiverHealth(
    onBecameReachable: () -> Unit = {},   // P6: shouldTriggerAutoSend が true のとき呼ぶ
): ReceiverHealthState                    // 中で LocalContext から ReceiverSettings を作って remember する
```

`MeterCaptureApp` は `fun MeterCaptureApp(queueStore: QueueStore, health: ReceiverHealthState = rememberReceiverHealth())` にする。引数が既定値つきなので、既存の呼び方（`MeterCaptureApp(queueStore)`）のままでも動く。`InspectionApp` から LegacyCapture として呼ぶときは、自分の `health` を渡し、疎通確認のループが2つ回らないようにする。

### 5.4 各画面

画面名・状態の型・純粋関数・見本の対応。文言は案Bの見本どおり。

**Home（P3）**（見本 01）

- Composable: `InspectionHomeScreen(state: HomeUiState, onCreate, onOpen: (AppScreen) -> Unit, onSettings, onGuide, onRoutes: (() -> Unit)?, onLegacy)`
- 状態:
  ```kotlin
  data class HomeCard(val inspectionId: String, val title: String, val stateLabel: String,
                      val subtitle: String, val progress: String?, val action: String, val target: AppScreen)
  data class HomeUiState(val inProgress: List<HomeCard>, val waiting: List<HomeCard>,
                         val sent: List<HomeCard>, val legacyUndelivered: String?)
  fun buildHomeUiState(items: List<InspectionListItem>, legacyItems: List<QueueItem>,
                       photosByInspection: Map<String, List<QueueItem>>): HomeUiState
  ```
- `subtitle`: 作業中は「大久保 ・ 第1工場 写真3枚 ・ 2機器」、送信待ちは「写真6枚 ・ 接続確認後に自動送信」、送信中は「写真6枚 ・ 2 / 6枚到着」、送信済みは「写真8枚 ・ すべてPCへ到着」、未到着ありは「写真8枚 ・ 1枚が未到着」。
- `progress`: ルートありの作業中だけ「対象3機器のうち2機器を撮影」。`observePhotoCounts` ではルートの機器のうち撮った数を出せないので、`InspectionApp` が既に購読している `queueStore.observeQueue()` の写真を `inspectionId` で分け、作業中の点検についてだけ `summarizeInspection`（ルートは `parseRouteJson(routeSnapshot)`）で出す。`buildHomeUiState` の引数に `photosByInspection: Map<String, List<QueueItem>>` を足す。P3ではルートが無いので常に null。
- `legacyUndelivered`: 点検に属さない写真の未着があれば「点検なしの写真: 未着N件」（`countUndelivered`）。押すと LegacyCapture。
- 並び: 各グループ内で `startedAt` の新しい順。

**Create（P3、P5でルート選択を追加）**（見本 02）

- Composable: `InspectionCreateScreen(state: CreateUiState, onNameChange, onOperatorChange, onPlaceChange, onRouteSelect: (String?) -> Unit, onStart, onBack)`
- 状態: `data class CreateUiState(val name: String, val namePlaceholder: String, val operatorName: String, val place: String, val routes: List<RouteChoice>, val selectedRouteId: String?, val error: String?, val starting: Boolean)`。`RouteChoice(routeId, label)`（label は「第1工場・3機器」）。
- 初期値: 点検名は空欄で、プレースホルダーに `defaultInspectionName`。担当者・場所は直前に作った点検の値（`observeInspections().first()` の先頭）を入れる。ルートは直前の点検のルートが保存済みならそれ、無ければ「ルートなし」。
- 入力はすべて任意（§9）。`normalizeInspectionText` が例外なら `error` に「64文字以内で入力してください」。
- 「点検を始める」→ `create` → Capture。

**Capture（P4）**（見本 03・03a・03b・03c、撮影ボタンは案A）

- Composable: `InspectionCaptureScreen(inspection: Inspection, photos: List<QueueItem>, health, initialTarget: CaptureTarget?, onSaved: suspend (File, CaptureMeta) -> Unit, onHistory, onComplete, onHome)`
- 撮影対象:
  ```kotlin
  // A/ui/inspection/CaptureTarget.kt（純粋関数）
  data class CaptureTarget(val deviceId: String?, val deviceName: String?, val source: String?)  // source: "qr" | "manual" | null
  fun CaptureTarget.toMeta(): CaptureMeta            // operatorValue・operatorNote は null
  fun targetFromQr(qr: DeviceQr): CaptureTarget       // source "qr"
  fun targetFromRoute(device: RouteDevice): CaptureTarget   // source "manual"
  fun targetFromPhoto(item: QueueItem): CaptureTarget       // 撮り直し。元の source を引き継ぐ
  fun manualTarget(name: String, id: String): Result<CaptureTarget>  // 名前1〜64、IDは空か isValidDeviceId。IDが空なら deviceId=null, source=null
  fun initialTarget(routeDevices: List<RouteDevice>?, photos: List<QueueItem>): CaptureTarget?  // ルートありは最初の未撮影、なしは null
  fun targetAfterCapture(routeDevices: List<RouteDevice>?, photosAfter: List<QueueItem>, captured: CaptureTarget?): CaptureTarget?
  //   ルートあり、かつ撮った機器がルートの機器 → 次の未撮影（無ければ null）。それ以外 → null（次のメーターに同じIDを付けてしまわないため）
  ```
- 状態: `data class CaptureUiState(val header: String, val progress: String, val missingChips: List<RouteDevice>, val targetName: String, val targetId: String, val countLine: String, val justSaved: SavedCard?)`。`fun buildCaptureUiState(inspection, routeDevices, photos, target, justSaved): CaptureUiState`。
  - `header`: 「11/06 朝の点検 ・ 作業中」
  - `progress`: ルートあり「対象 3機器中 2機器を撮影」、なし「写真3枚 ・ 2機器」
  - `targetName`／`targetId`: 対象なしなら「機器が選ばれていません」／「QRを読むか、手入力してください」
  - `countLine`: 「この点検：写真3枚 ・ 2機器」
- 配置（上から）: 帯、題名、`header`、`progress`、未撮影の機器のチップ（ルートありだけ。押すと `targetFromRoute`）、「機器QRを読む」（既存の `DeviceQrSection(held = null, onScanningChange, onUse = { target = targetFromQr(it) }, onClear = {})` をそのまま使う、F15）、対象のカード（名前・ID・「機器名・IDを手入力する」）、カメラのプレビュー（`CameraCapturePanel(large = true, ...)`）、`countLine`、「この点検の履歴を見る」、「点検完了へ」。
- 大きな撮影ボタン: `CameraCapturePanel` に `large: Boolean = false` を足す（§7.2）。`large = true` のとき、ボタンは横幅いっぱい・高さ88dp以上・文字は `headlineSmall`、文言「撮影する」（保存中は「保存中...」）。
- 手入力: `ManualDeviceDialog`（同じファイル内の private Composable）。機器名と機器ID（任意）の2つの入力欄。誤りは「機器IDは英数字と . _ - で32文字以内です」。
- 撮影後: `inspectionStore.addPhoto(inspection.inspectionId, file, target.toMeta())` → 成功で `justSaved` を出す（見本03c。写真・機器名・ID・時刻、写真の枚数・撮影済みの機器数、「次の機器を撮る」「履歴を確認する」「点検完了へ」）。「次の機器を撮る」で `justSaved = null`、対象は `targetAfterCapture`。失敗は既存と同じく赤字で「保存に失敗しました: …」。点検の写真は撮影時に `enqueueSend` を呼ばない（送らないため）。
- 真値（`operatorValue`）の入力欄は出さない（§9）。

**History（P4）**（見本 04・04a・04b）

- Composable: `InspectionHistoryScreen(state: HistoryUiState, onPhotoClick: (QueueItem) -> Unit, onRetake: (QueueItem) -> Unit, onShootDevice: (RouteDevice) -> Unit, onDelete: (QueueItem) -> Unit, onBackToCapture, onComplete, onHome)`
- 状態:
  ```kotlin
  data class RouteCheckRow(val device: RouteDevice, val count: Int, val done: Boolean)
  data class HistoryRow(val item: QueueItem, val title: String, val idLine: String, val timeLine: String,
                        val sourceLabel: String, val canEdit: Boolean)
  data class HistoryUiState(val header: String, val photoCount: Int, val deviceLine: String,
                            val routeRows: List<RouteCheckRow>?, val rows: List<HistoryRow>,
                            val notices: List<String>, val noRouteNote: String?)
  fun buildHistoryUiState(inspection: Inspection, routeDevices: List<RouteDevice>?, photos: List<QueueItem>): HistoryUiState
  fun deviceSourceLabel(item: QueueItem, routeIds: Set<String>): String
  //   qr → "QR"、manual かつ ID がルートにある → "一覧から"、manual → "手入力"、ID なし → "機器IDなし"
  ```
- `deviceLine`: ルートあり「2 / 3機器」、なし「2機器」。`notices`: 重複ごとに「A-101は2枚あります。撮り直しの写真か確認してください。」。`noRouteNote`: ルートなしのとき「写真3枚・撮影済み2機器と表示します。未撮影の機器は判定できません。」は出さず、短く「対象一覧がないため、未撮影の機器は判定できません」。
- 写真の行: サムネイル（`QueueListScreen.kt` の `Thumbnail` を internal にして使う、§7.2）、機器名（無ければ「機器名なし」）、機器ID、「11/06 09:32 撮影」、出所、「撮り直す」「削除」（`canEdit` = 点検が作業中）。行を押すと既存の `FullImageDialog`。
- 撮り直し: `pendingTarget = targetFromPhoto(item)` → Capture。元の写真は残る（§9）。
- 削除: 確認ダイアログ（このファイル内の private Composable）。文言は見本どおり「この写真と紐づく機器の情報を、この点検の履歴から削除します。」と、写真・機器名・ID・時刻。「削除する」で `deletePhoto`。

**Complete（P4）**（見本 05）

- Composable: `InspectionCompleteScreen(state: CompleteUiState, onBackToHistory, onComplete)`
- 状態: `data class CompleteUiState(val title: String, val photoCount: Int, val deviceCount: Int, val warnings: List<String>, val canComplete: Boolean, val completeLabel: String, val blockReason: String?)`。`fun buildCompleteUiState(inspection, summary: InspectionSummary): CompleteUiState`。
- `warnings`（この順）: 「未撮影：冷却水温度計 A-103」（1機器1行）、「重複：ボイラー圧力計 A-101 が2枚」、「一覧外：Z-9」、「機器IDなし：N枚」、ルートなしは「対象一覧がないため、未撮影は確認できません」。
- `completeLabel`: 注意があれば「確認して点検を完了する」、無ければ「点検を完了する」。写真0枚は `canComplete = false`、`blockReason = "写真がありません。撮影してから完了してください"`。
- 説明文「完了すると送信待ちになります。PCに届く接続が確認できたら、自動で送信します。」
- 完了: `complete` → `enqueueSend` → SendStatus。

**SendStatus（P6。P4では仮の表示）**（見本 05a・06・06a・06b）

P4の時点（P6の前）は、完了後に「送信待ち」の見出しと写真の一覧だけを出す簡単な表示にする（P4単独で完了まで動かすため）。P6で次の形にする。

- Composable: `InspectionSendStatusScreen(state: SendStatusUiState, onSendNow, onRetryUndelivered, onReassign: (String) -> Unit, onGuide, onHome)`
- 状態:
  ```kotlin
  data class SendStatusUiState(
      val badge: String,             // 送信待ち／送信中／送信済み／送信済み（一部失敗あり）
      val headline: String,          // 「点検を完了しました」「PCへ送っています」「すべてPCに届きました」「1枚が届いていません」
      val summaryLine: String,       // 「大久保 ・ 第1工場 写真3枚 ・ 2機器」
      val photoProgress: String,     // 「2 / 3枚」「写真 3 / 3枚 到着」
      val manifestLine: String,      // 「写真の一覧：到着」「写真の一覧：未送信 残りの写真が届いたら送ります。」「写真の一覧：送れませんでした（理由）」
      val guidance: String?,         // 接続に応じた案内（下）
      val rows: List<SendRow>,       // 写真ごと（未到着だけ／全部）
      val showSendNow: Boolean,
      val showRetryUndelivered: Boolean,
      val showManifestOnlyRetry: Boolean,
      val showGuideLink: Boolean,
  )
  data class SendRow(val item: QueueItem, val title: String, val idLine: String, val timeLine: String, val status: String, val heldForOtherPc: Boolean)
  fun buildSendStatusUiState(inspection: Inspection, photos: List<QueueItem>, health: HealthView, currentReceiverId: String?, pcName: String?): SendStatusUiState
  data class HealthView(val reachable: Boolean?, val network: NetworkSnapshot)
  ```
- `guidance`（WAITINGのとき）: 届く → 「まもなく送信します」。Wi-Fi等あり・届かない → 「Wi-Fiには接続していますが、PCに届きません。PCの受信アプリと接続を確認してください。」（接続の種類の名前を差し込む）。未接続 → 「PCにつながりません。接続の案内を見てください」＋`showGuideLink`。別PC宛ての写真がある → 「別のPC宛ての写真があります。『今のPCへ送り直す』で送れます」。
- 写真の状態の文言は既存の `sendStatusLabel`（`QueueDisplay.kt:8-18`）を使う。
- `showRetryUndelivered`: SENT_INCOMPLETE。ボタン「届いていない写真を再送」。
- `showManifestOnlyRetry`: WAITING で写真がすべて `SENT`/`http`、`manifestError != null`。ボタン「写真の一覧だけ再送」（`enqueueSend`）。
- SENT のとき: 「写真 3 / 3枚 到着 写真の一覧 到着 送信先：<PC名> ・ HH:mm（manifestSentAt）」。PC名は `ReceiverSettings.getPcName()`、無ければURLのホスト。

**ConnectionGuide（P6）**（見本 07）

- Composable: `ConnectionGuideScreen(networkLabel: String, reachable: Boolean?, onHome, onSettings)`。固定文言は見本どおりの3手順。下に「今の接続: <networkLabel>　PCに届きます／届きません」。

**Routes（P5）**（§6.3）

### 5.5 既存画面との関係

| 既存 | 扱い |
|---|---|
| `MeterCaptureApp`（撮影・機器QR・設定・送信先QR・履歴） | 入口ではなくなる。Homeの「点検なしで撮る（従来の画面）」から開く LegacyCapture として残す（要確認1）。中身は §5.3 の2つの切り出しだけ変える |
| `QueueListScreen`（全写真の履歴） | LegacyCapture の「履歴」から開く。`LegacyQueueView` により点検に属さない写真だけを出す。点検の写真の操作は点検の画面で行う |
| 送信先の設定ダイアログ・`PairingScreen` | `ReceiverSettingsDialog` に切り出し、Home・ConnectionGuide・LegacyCapture から開く。`PairingScreen` は変えない |
| 機器QR（`DeviceQrSection`・`QrScanPanel`） | Capture でそのまま使う。保持中の機器（`DeviceIdSettings`）は点検の撮影では使わない |
| `ConnectionBar`・`ConnectionStatus` | そのまま使う。文言の結合だけ新関数（§4.5） |

---

## 6. 点検ルート（P5）

### 6.1 受け取り

| 経路 | 処理 |
|---|---|
| Wi-Fi | `RouteClient.listRoutes()` → `GET /routes`（`X-Sotuken-Token`）→ 一覧を表示 → 選ぶ → `RouteClient.fetchRoute(id)` → `GET /routes/<id>` → 確認 → 保存 |
| QR | `QrScanPanel` で読む → `parseRouteQr(raw)` → 確認 → 保存 |

```kotlin
// A/route/RouteJson.kt（P3で作る。点検の routeSnapshot を読むのに要るため）
data class RouteDoc(val routeId: String, val name: String, val devices: List<RouteDevice>, val updatedAt: String)
fun parseRouteJson(text: String): RouteDoc?       // 不正なら null
fun RouteDoc.toJson(): String                     // {"v":1,"route_id","name","devices":[{"id","name"}],"updated_at"}

// A/route/RouteQr.kt（P5）
const val ROUTE_QR_PREFIX = "SOTUKEN-ROUTE:"
sealed interface RouteQrResult { data class Ok(val route: RouteDoc) : RouteQrResult; data class Error(val message: String) : RouteQrResult }
fun parseRouteQr(raw: String): RouteQrResult

// A/route/RouteClient.kt（P5）
data class RouteSummary(val routeId: String, val name: String, val count: Int, val updatedAt: String)
class RouteClient(private val baseUrl: String, private val token: String,
                  private val openConnection: (URL) -> HttpURLConnection = { it.openConnection() as HttpURLConnection }) {
    suspend fun listRoutes(): Result<List<RouteSummary>>
    suspend fun fetchRoute(routeId: String): Result<RouteDoc>
}
fun parseRouteList(text: String): List<RouteSummary>?
```

検証（`parseRouteJson`・`parseRouteList` 共通）:
- `v` は数値の1（`DeviceQr.kt:44-45` と同じ判定）。
- `route_id` は `[A-Za-z0-9._-]{1,64}`。`name` は前後空白を除いて1〜64文字、制御文字なし。`updated_at` は空でない文字列（中身は解釈せず表示だけ）。
- `devices` は1〜200件。各 `id` は機器IDの規則（`isValidDeviceId`）、`name` は機器名の規則（`validDeviceNameOrNull`）。どちらも `DeviceQr.kt` の private 規則を公開関数にしたもの（§7.2）。同じ `id` が2回あれば不正。
- 知らないキーは無視する。
- QRは接頭辞が完全一致で、全体が2,048バイト以下（PCは1,500バイトを超えるときQRを出さない取り決め）。接頭辞が違えば「ルートのQRではありません」。機器QR・送信先QRと取り違えたときもこの文言。
- `RouteClient`: 送信先は §4.3 の `pickReachableUrl` で選んだURL。リダイレクト禁止、接続2秒・読み取り5秒、本文は256KiBまで。401・403 →「合言葉が違います」、404 →「PCがルートの受け渡しに未対応です。PCのアプリを更新してください」、通信失敗 →「PCに接続できません」。

### 6.2 保存

- 保存先: アプリ内部の `filesDir/routes.json`（1ファイル）。DBの表にしない。ルートは数件・数KBで、検索も要らないため。Roomのバージョンを上げずに済む。
- 形: `{"v":1,"routes":[{...RouteDocのJSON..., "saved_at":"<ISO>", "source":"wifi"|"qr"}]}`。
- `A/route/RouteRepository.kt`:
  ```kotlin
  data class SavedRoute(val route: RouteDoc, val savedAt: String, val source: String)
  class RouteRepository(private val file: File) {
      fun load(): List<SavedRoute>                   // 壊れていれば空（壊れたファイルは routes.json.broken に改名して残す）
      fun save(route: RouteDoc, source: String, now: Instant): List<SavedRoute>  // 同じ routeId は置き換え
      fun delete(routeId: String): List<SavedRoute>
  }
  ```
  書き込みは `routes.json.tmp` に書いてから `renameTo`。`@Synchronized`。画面からは `Dispatchers.IO` で呼ぶ。
- 点検の作成時に、選んだルートの `RouteDoc.toJson()` を `Inspection.routeSnapshot` にコピーする。以後、その点検はコピーだけを使う（ルートを更新・削除しても作業中の点検は変わらない）。

### 6.3 画面

- Composable: `RouteListScreen(state: RouteListUiState, onFetchList, onPick: (String) -> Unit, onScanQr, onDelete: (String) -> Unit, onBack)`、状態は `data class RouteListUiState(val saved: List<SavedRouteRow>, val remote: List<RouteSummary>?, val loading: Boolean, val error: String?, val confirm: RouteDoc?)`。
- 上: 保存済みのルート（名前・機器数・`updated_at`・取得方法、削除ボタン）。下: 「PCから取得」（一覧 → 選ぶ → 確認）と「ルートのQRを読む」。確認ダイアログには名前・機器数・最初の5機器を出し、「保存する」で保存。
- 同じ `route_id` が既にあれば「保存済みのルートを新しい内容で置き換えます。作成済みの点検には影響しません。」と出す。

### 6.4 ルートなしの点検

`routeId`・`routeName`・`routeSnapshot` が null。進捗は「写真N枚 ・ M機器」、未撮影の判定と追加は出さない（見本の「対象一覧がない場合」）。manifest は `route_id: null`、`missing: []`、`extra: []`。

---

## 7. PR分割の詳細（P3 → P4 → P5 → P6）

各PRは単独で `gradlew test --rerun-tasks` と `assembleDebug` が通ること。既存の単体テスト（debug 162＋release 162）は**期待値を変えずに**通すこと。androidTest は端末が要るので、§8の移行テストは実機かエミュレーターで `connectedDebugAndroidTest` を流し、結果をPRに書く（流せなければ「未実行」と書く）。

### 7.1 P3: 点検のデータとRoom、一覧と作成の画面

新規:
- `A/inspection/Inspection.kt`（`Inspection`、`InspectionState`、`InspectionStateConverter`、`RouteDevice`）
- `A/inspection/InspectionDao.kt`（`requeueSent` を除く §1.4）
- `A/inspection/InspectionStateMachine.kt`（§2.2）
- `A/inspection/InspectionSendRules.kt`（§2.3）
- `A/inspection/InspectionSummary.kt`（§2.4）
- `A/inspection/InspectionNaming.kt`（§2.5）
- `A/inspection/InspectionStore.kt`（`create`・`addPhoto`・`complete`・`delete`・observe 3つ）
- `A/route/RouteJson.kt`（`RouteDoc`・`parseRouteJson`・`toJson`）
- `A/ui/ReceiverHealth.kt`、`A/ui/ReceiverSettingsDialog.kt`
- `A/ui/inspection/AppScreen.kt`、`InspectionApp.kt`、`InspectionScaffold.kt`、`InspectionHomeScreen.kt`、`InspectionCreateScreen.kt`、`InspectionDisplay.kt`（`buildHomeUiState`・`inspectionStateLabel`）、`LegacyQueueView.kt`
- テスト（§8）と `T/inspection/FakeInspectionDao.kt`（`FakeQueueDao` を受け取り、写真の検索はそこから引く）

変更:
- `A/queue/QueueItem.kt`: 3列と索引、`CaptureMeta` に3つ（既定値 null）。
- `A/queue/QueueStore.kt`: `enqueue` で3つを写す（`:79-96`）。インターフェースは不変。
- `A/queue/CaptureDatabase.kt`: §1.3。
- `A/queue/SendRouter.kt`: `isSendable`（§3.1）。
- `A/queue/QueueSendWorker.kt`: `getInstance`、`close` を消す、`isSendable` を渡す。
- `A/queue/sender/SenderPayloads.kt`: §3.2。
- `A/MainActivity.kt`: `getInstance`、`RoomInspectionStore` を作り `InspectionApp` を表示。
- `A/ui/MeterCaptureApp.kt`: `:79-131` を `rememberReceiverHealth` の呼び出しへ、`:309-386` を `ReceiverSettingsDialog` の呼び出しへ置き換え、引数に `health` を足す。他は触らない。
- `AT/queue/RoomQueueStoreInstrumentedTest.kt:45`: `.addMigrations(CaptureDatabase.MIGRATION_1_2)` を `.addMigrations(*CaptureDatabase.ALL_MIGRATIONS)` に（F20）。

公開シグネチャの変更と影響を受ける呼び出し元:
- `SendRouter(...)` に末尾の既定値つき引数 → 呼び出し元 `QueueSendWorker.kt:62`、`SendRouterTest.kt` の全 `SendRouter(` は変更不要。
- `MeterCaptureApp(queueStore)` に既定値つき引数 → 呼び出し元 `MainActivity.kt:28`（P3で `InspectionApp` に替わる）、`InspectionApp`（新規）。
- `CaptureMeta(...)` に既定値つき引数 → 呼び出し元 `MeterCaptureApp.kt:218`、テスト内の `CaptureMeta(` は変更不要。
- `QueueItem(...)` に既定値つき引数 → 位置引数・名前つきの既存の呼び出しはすべて変更不要（F1）。

P3の時点の動き: 点検を作ると Capture へ進むが、Capture 画面は P4 で作るので、P3では「この点検で撮影する画面は次の更新で入ります」と表示し、点検の削除だけできる仮画面にする（`InspectionPlaceholderScreen` を `InspectionApp.kt` の中の private Composable として置き、P4で消す）。従来の撮影は LegacyCapture から今までどおり使える。

### 7.2 P4: 点検中の撮影・履歴・完了確認

新規:
- `A/ui/inspection/CaptureTarget.kt`、`InspectionCaptureScreen.kt`、`InspectionHistoryScreen.kt`、`InspectionCompleteScreen.kt`
- `InspectionDisplay.kt` に `buildCaptureUiState`・`buildHistoryUiState`・`buildCompleteUiState`・`deviceSourceLabel` を追加
- 仮の SendStatus（§5.4。`InspectionApp.kt` の private Composable）

変更:
- `A/inspection/InspectionStore.kt`: `deletePhoto`。
- `A/ui/CameraCapturePanel.kt`: 引数に `large: Boolean = false`。`:114-135` の `Button` に `modifier = if (large) Modifier.fillMaxWidth().heightIn(min = 88.dp) else Modifier` と、文言・文字の大きさの出し分けだけを足す。既存の呼び出し元（`MeterCaptureApp.kt:212`、`QrScanPanel.kt:55`）は変更不要。
- `A/ui/QueueListScreen.kt`: `private fun Thumbnail`（`:271`）と `private fun FullImageDialog`（`:304`）の `private` を `internal` に。中身は変えない。
- `A/device/DeviceQr.kt`: `fun isValidDeviceId(id: String): Boolean` と `fun validDeviceNameOrNull(raw: String): String?` を公開し、`parseDeviceQr` はこれを使う（判定は今と同じ。`DeviceQrTest` の期待値は不変）。
- `A/ui/inspection/InspectionApp.kt`: 仮画面を Capture・History・Complete に差し替え、`pendingTarget`。
- `A/queue/sender/SenderPayloads.kt:34`: コメントだけ（§3.2）。

### 7.3 P5: ルートの取得とQR取り込み、保存

新規: `A/route/RouteQr.kt`、`A/route/RouteClient.kt`、`A/route/RouteRepository.kt`、`A/ui/inspection/RouteListScreen.kt`（`RouteListUiState` の組み立て関数を含む）、`A/settings/ReceiverUrlCandidates.kt` のうち `pickReachableUrl`（ルート取得でも使うため、ここで入れる。候補の保存は P6）。

変更: `InspectionCreateScreen.kt`（ルートの選択）、`InspectionApp.kt`（Routes への遷移）、`AppScreen.kt`（`Routes` の encode/decode）、`MainActivity.kt`（`RouteRepository(File(filesDir, "routes.json"))` を渡す）、`InspectionStore.create`（`NewInspection.route` を `routeId`・`routeName`・`routeSnapshot` にコピー）、`InspectionDisplay.kt`（`buildHomeUiState` の進捗にルートを使う）。

PCのP2が入っていなくても、QRの取り込みと保存・点検の作成までは動く（Wi-Fi取得は404の文言になる）。

### 7.4 P6: 自動送信・manifest・一部失敗の再送・接続表示

新規: `A/inspection/InspectionManifest.kt`、`A/inspection/InspectionSendCoordinator.kt`、`A/ui/NetworkStatus.kt`、`A/ui/inspection/InspectionSendStatusScreen.kt`、`A/ui/inspection/ConnectionGuideScreen.kt`、`ReceiverUrlCandidates.kt` の `mergeCandidateUrls`。

変更:
- `A/queue/sender/HttpSender.kt`: `postManifest`、409 を恒久エラーに。
- `A/queue/QueueSendWorker.kt`: §3.1 の P6 の流れ。
- `A/inspection/InspectionDao.kt`: `requeueSent`。`A/inspection/InspectionStore.kt`: `retryUndelivered`。
- `A/settings/ReceiverSettings.kt`: `KEY_ALT_URLS`、`savePaired`・`save` の候補の扱い、`SendTarget.candidateUrls`（§4.3）。
- `A/ui/ReceiverHealth.kt`: 接続の種類、候補URLでの確認、`onBecameReachable`。
- `A/ui/inspection/InspectionApp.kt`・`InspectionScaffold.kt`: 帯の文言を `connectionBarTextWithNetwork` に、未着の数え方（§4.5）、仮の SendStatus を本物に差し替え、ConnectionGuide。
- `A/ui/MeterCaptureApp.kt`: 変更なし（帯の文言は `health.network` を使わない既存のまま。従来画面なので）。

### 7.5 衝突を避ける方針

- `MeterCaptureApp.kt` を触るのは P3 の2か所（疎通確認と設定ダイアログの切り出し）だけ。切り出しは中身を変えずに移すので、他の人の変更と衝突しても解消しやすい。
- `QueueListScreen.kt` を触るのは P4 の `private` → `internal` の2語だけ。
- 新しい画面・ロジックはすべて新ファイル。`InspectionApp.kt` は P3〜P6 で毎回触るが、この作業の外の人は触らないファイル。
- 各PRの前に `origin/main` を取り込み、`MeterCaptureApp.kt`・`QueueListScreen.kt`・`SendRouter.kt`・`HttpSender.kt`・`ReceiverSettings.kt` の差分を確かめる。

---

## 8. テスト項目

置き場所は `T/`（JVM単体）と `AT/`（端末）。名前は JUnit4 の関数名。

### P3

| ファイル | テスト |
|---|---|
| `T/inspection/InspectionStateMachineTest.kt` | `completeMovesInProgressToWaiting`、`startSendingMovesWaitingToSending`、`recoverMovesSendingToWaiting`、`roundUnfinishedMovesSendingToWaiting`、`manifestAcceptedWithZeroUndeliveredIsSent`、`manifestAcceptedWithUndeliveredIsSentIncomplete`、`retryUndeliveredMovesSentIncompleteToWaiting`、`completeFromWaitingThrows`、`noEventReturnsToInProgress`、`sentAcceptsNoEvent`、`startSendingFromInProgressThrows` |
| `T/inspection/InspectionSendRulesTest.kt` | `photoWithoutInspectionIsSendable`、`inProgressPhotoIsNotSendable`、`waitingAndSendingPhotosAreSendable`、`sentAndIncompletePhotosAreNotSendable`、`photoOfMissingInspectionIsSendable` |
| `T/inspection/InspectionSummaryTest.kt` | `countsPhotosAndDistinctDevices`、`deviceNameOnlyPhotosCountByName`、`photosWithoutIdAndNameAreUnidentifiedAndNotDevices`、`missingFollowsRouteOrder`、`nameMatchDoesNotSatisfyRouteDevice`、`duplicatesListDevicesWithTwoOrMorePhotos`、`extraListsIdsOutsideRouteInCaptureOrder`、`noRouteHasNullRouteCountsAndEmptyMissingExtra`、`summaryJsonRoundTrips` |
| `T/inspection/InspectionNamingTest.kt` | `inspectionIdMatchesPatternAndIsUtc`、`timeSlotBoundaries`（3:59 夜・4:00 朝・10:59 朝・11:00 昼・14:59 昼・15:00 夕方・18:59 夕方・19:00 夜）、`defaultNameUsesLocalDate`、`defaultNameAddsSequenceWhenTaken`（「11/06 朝の点検」「… 2」があれば「… 3」）、`normalizeTextTrimsAndRejectsLongOrControl` |
| `T/inspection/RoomInspectionStoreTest.kt` | `createStoresInProgressWithDefaultName`、`createKeepsTypedName`、`addPhotoCopiesInspectionFieldsToQueueItem`、`addPhotoToCompletedInspectionThrows`、`completeSavesSummaryAndCompletedAt`、`completeWithoutPhotosThrowsAndKeepsState`、`deleteInProgressRemovesPhotosThenInspection`、`deleteWaitingInspectionIsRejected`、`observeInspectionsJoinsCounts` |
| `T/queue/SendRouterInspectionGateTest.kt` | `inProgressPhotoStaysPendingAndIsNotWrittenToOutbox`、`waitingPhotoIsSentOverHttp`、`legacyPhotoIsSentAsBefore`、`catchUpSkipsNonSendablePhotos`、`defaultGateKeepsExistingBehavior` |
| `T/queue/sender/InspectionSidecarTest.kt` | `sidecarIncludesInspectionIdNameAndRoute`、`sidecarOmitsRouteIdWhenNoRoute`、`sidecarUnchangedWhenNoInspection`（既存の出力と文字列で一致） |
| `T/route/RouteJsonTest.kt` | `parsesValidRoute`、`rejectsVersionOtherThanOne`、`rejectsBadRouteId`、`rejectsEmptyOrTooManyDevices`、`rejectsDuplicateDeviceIds`、`rejectsInvalidDeviceIdOrName`、`ignoresUnknownKeys`、`toJsonRoundTrips` |
| `T/ui/inspection/AppScreenTest.kt` | `encodeDecodeRoundTripsAllScreens`、`unknownTextDecodesToHome`、`resolveSendsMissingInspectionHome`、`resolveRedirectsCaptureOfCompletedInspectionToSendStatus` |
| `T/ui/inspection/HomeUiStateTest.kt` | `groupsByState`、`sortsNewestFirstWithinGroup`、`inProgressSubtitleShowsOperatorPlaceAndCounts`、`waitingSubtitleMentionsAutoSend`、`sentIncompleteShowsUndeliveredCount`、`legacyUndeliveredShownOnlyWhenPositive` |
| `T/ui/inspection/LegacyQueueViewTest.kt` | `observeQueueHidesInspectionPhotos` |
| `AT/queue/CaptureDatabaseMigrationTest.kt` | `migration4To5KeepsPhotosWithNullInspection`（v4の表を手で作り行を入れ、v5で開いて読めること・3列がNULL）、`migration4To5CreatesInspectionsTableAndIndex`（`inspections` に挿入・取得でき、`index_queue_items_inspectionId` が `sqlite_master` にある）、`migrationFromVersionOneReachesFive` |
| `AT/inspection/InspectionDaoInstrumentedTest.kt` | `photoCountsMatchSummarizeInspection`（同じ写真で `observePhotoCounts` と `summarizeInspection` の枚数・機器数が一致）、`observePhotosOrdersByCapturedAt`、`findByStateAndResetState` |

### P4

| ファイル | テスト |
|---|---|
| `T/ui/inspection/CaptureTargetTest.kt` | `qrTargetHasQrSource`、`routeTargetHasManualSource`、`manualTargetWithoutIdHasNoSource`、`manualTargetRejectsInvalidId`、`retakeKeepsDeviceAndSource`、`initialTargetIsFirstMissingRouteDevice`、`afterCaptureAdvancesToNextMissing`、`afterCaptureWithoutRouteClearsTarget`、`afterCaptureOfLastMissingIsNull` |
| `T/ui/inspection/CaptureUiStateTest.kt` | `routeProgressText`、`noRouteProgressText`、`missingChipsOnlyWithRoute`、`emptyTargetTexts` |
| `T/ui/inspection/HistoryUiStateTest.kt` | `routeRowsMarkDoneAndCounts`、`duplicateNoticePerDevice`、`sourceLabels`（QR・一覧から・手入力・機器IDなし）、`editDisabledAfterCompletion`、`noRouteNote` |
| `T/ui/inspection/CompleteUiStateTest.kt` | `warningsInFixedOrder`、`labelChangesWhenWarningsExist`、`zeroPhotosBlocksCompletion`、`noRouteWarning` |
| `T/inspection/RoomInspectionStoreTest.kt`（追加） | `deletePhotoOnlyWhileInProgress`、`deletePhotoOfOtherInspectionIsNotFound` |
| `T/device/DeviceQrTest.kt`（追加） | `isValidDeviceIdMatchesQrRule`、`validDeviceNameOrNullTrimsAndRejects` |

### P5

| ファイル | テスト |
|---|---|
| `T/route/RouteQrTest.kt` | `parsesPrefixedRoute`、`rejectsMissingPrefix`、`rejectsDeviceQrAndPairingQr`、`rejectsOver2048Bytes`、`rejectsBrokenJson` |
| `T/route/RouteClientTest.kt`（`HttpSenderTest` と同じ `ServerSocket` 方式） | `listSendsTokenAndParses`、`fetchParsesRoute`、`unauthorizedMapsToTokenMessage`、`notFoundMapsToUnsupportedMessage`、`doesNotFollowRedirect`、`rejectsOversizedBody` |
| `T/route/RouteRepositoryTest.kt`（一時ディレクトリ） | `saveThenLoad`、`saveReplacesSameRouteId`、`deleteRemoves`、`brokenFileLoadsEmptyAndIsKept` |
| `T/inspection/RoomInspectionStoreTest.kt`（追加） | `createCopiesRouteSnapshot`、`laterRouteUpdateDoesNotChangeInspection` |
| `T/settings/ReceiverUrlCandidatesTest.kt` | `pickReachableReturnsFirstSuccess`、`pickReachableReturnsLastErrorWhenNone` |

### P6

| ファイル | テスト |
|---|---|
| `T/inspection/InspectionManifestTest.kt` | `buildsContractKeysInOrder`、`nullsForMissingOptionalValues`、`noRouteHasEmptyMissingAndExtra`、`includesFailedPhotos`、`sha256NullWhenFileMissing`、`parseReplyReadsMatchedAndMissing`、`parseReplyRejectsOkFalse` |
| `T/inspection/InspectionSendCoordinatorTest.kt` | `beforeRouteRecoversSending`、`beforeRouteMarksWaitingAsSendingOnlyWhenReachable`、`unfinishedRoundReturnsToWaiting`、`folderOnlyPhotoKeepsWaiting`、`heldPhotoKeepsWaiting`、`allDeliveredSendsManifestAndMarksSent`、`failedPhotoSendsManifestAndMarksIncomplete`、`pcMissingPhotosMarkIncomplete`、`manifestFailureKeepsWaitingWithError`、`noPosterKeepsWaitingWithError`、`decideAfterRoundRules` |
| `T/inspection/RoomInspectionStoreTest.kt`（追加） | `retryUndeliveredRequeuesFailedAndPcMissing`、`retryUndeliveredFromSentThrows` |
| `T/queue/sender/HttpSenderTest.kt`（追加） | `postManifestSendsJsonAndToken`、`postManifestParsesReply`、`postManifest404IsTemporaryWithUpdateMessage`、`postManifestRejectsInvalidInspectionId`、`upload409IsPermanent` |
| `T/ui/NetworkStatusTest.kt` | `labels`（Wi-Fi・USBテザリング・両方・有線LAN・未接続）、`usbTetherInterfaceNames`（rndis0・usb0・ncm0 は真、wlan0・rmnet0 は偽）、`barTextPrefixesNetwork`、`autoSendTriggersOnlyOnEdgeWithWork` |
| `T/settings/ReceiverUrlCandidatesTest.kt`（追加） | `samePcMovesOldUrlToCandidates`、`otherPcClearsCandidates`、`keepsAtMostThreeWithoutDuplicates` |
| `T/settings/ReceiverSettingsTest.kt`（追加） | `manualSaveClearsCandidates`、`sendTargetListsPrimaryThenCandidates` |
| `T/ui/inspection/SendStatusUiStateTest.kt` | `waitingReachable`、`waitingWifiButUnreachable`、`waitingOffline`、`sendingProgress`、`sentShowsManifestArrived`、`incompleteShowsRetry`、`manifestOnlyRetryWhenPhotosDelivered`、`heldPhotoGuidance` |

---

## 9. 未決だった既定値（設計として確定）

| 項目 | 決定 | 理由 |
|---|---|---|
| 点検名の自動採番 | 「MM/dd 朝の点検」。時間帯は朝4:00〜10:59、昼11:00〜14:59、夕方15:00〜18:59、夜それ以外。同じ名前があれば「 2」「 3」を付ける。名前は作成後に変えない | 見本の表記に合わせ、識別は点検IDで行うので名前は読みやすさを優先した |
| 撮り直し | 元の写真を残し、別の写真として追加する。完了確認で「重複：… が2枚」と出す | 置き換えると読み取りに使える写真を失う。どれを採るかはPC側で選べる |
| 完了後の再開 | できない（完了＝確定）。撮影・削除は作業中だけ | 送信中・送信後の写真が変わると、manifestとPCの記録が食い違う |
| ルートの更新が作業中の点検に及ぶか | 及ばない。作成時にコピーした `routeSnapshot` を使う | 点検の途中で未撮影の判定が変わらないようにする |
| 作成時の必須項目 | なし（点検名は空欄なら自動、担当者・場所は任意） | 見本で必須が未確定。現場で入力に詰まらせない。担当者・場所は直前の値を入れておく |
| 写真0枚の完了 | できない。0枚の点検は削除する | 空のmanifestをPCへ送っても意味がない |
| 点検の削除 | 作業中だけ（写真も消す）。送信済みの片付けは初版では作らない | 届いていない写真を消す事故を防ぐ |
| 点検中の真値の入力 | 出さない | 見本に無く、現場の点検では使わない。評価用の撮影は従来の画面で入れられる |
| ルートの機器を選んで撮った写真の出所 | `manual` | 取り決めの値は `qr`・`manual` だけ（F18）。QRで確かめていないので `qr` にしない。画面ではルートにあるIDなら「一覧から」と表示する |
| 自動再試行 | FAILEDは自動で戻さない。一時的な失敗は送信箱経由で、接続のたびに追い送り | 既存方針（送信機構レビュー P1）に合わせる |
| 409（同名で内容が違う） | 恒久エラー（FAILED） | 何度送っても通らない（F7） |
| 点検IDの形 | `INS-yyyyMMddTHHmmssZ-<16進8桁>` | 取り決めの文字種と長さを満たし、複数台で衝突しない |
| ルートの保存先 | `filesDir/routes.json` | DBのバージョン上げを1回（4→5）に抑える。件数が少ない |
| ViewModel | 使わない | 既存の書き方に合わせ、依存を増やさない |

---

## 10. リスクと落とし穴

| リスク | 内容 | 対策 |
|---|---|---|
| Roomの移行の失敗 | CREATE文がRoomの期待とずれると、起動時に `IllegalStateException` でアプリが開かない。`fallbackToDestructiveMigration` を使っていないので、DBは消えずに残るが、アプリは使えない | §8の移行テストを端末で流してからマージする。F20の既存テストの組み立ても直す。撮影画像のファイルは `Pictures/` 側に残るので、最悪の場合もUSBで取り出せる |
| 画面に送信状態が届かない | F8（Worker と画面が別のDBインスタンス）。送信中の進み具合が更新されない | P3で `getInstance` に一本化する。実機で「送信中 2/3枚」が進むことを確かめる |
| 送信中のアプリ終了 | 写真が SENDING、点検が SENDING のまま残る | 写真は既存の `recoverInterruptedSends`、点検は `beforeRoute` で WAITING に戻す |
| 同じ写真の二重送信 | 応答が失われた後の追い送り、PCの `missing_photos` からの再送 | PCは同名・同内容に `200 duplicate`（F7）。manifestは上書き |
| 画像ファイルが無い写真 | `HttpSender.send` の `FileNotFoundException` は `IOException` なので、既存の `SendRouter.kt:75-78` がその回の残りを「PCに届かない」扱いにする（既存の動き） | この設計では直さない（範囲外）。manifestでは `sha256: null` で未着になる。気づいたら別の課題に |
| 点検の削除 | 写真の削除の途中で失敗すると、写真の一部だけが消える | 1枚ずつ消し、`DELETED` 以外が返ったら止めて点検の行を残す。もう一度削除すれば続きから消える |
| 時計のずれ | 端末の時計が狂うと、点検名の日付・`capturedAt`・ファイル名の時刻がずれる | 識別は点検IDの乱数部と `localId`（UUID）で行うので、照合には影響しない。PCは時刻を表示にだけ使う |
| ルートの更新との整合 | PCでルートを直した後に届いたmanifestの `missing` は、スマホの作成時のコピーで計算されている | PC（P2）はmanifestの `missing`・`extra` をそのまま記録し、今のルートで計算し直さない。§11でP2へ伝える |
| USBテザリングの検出 | 網の名前は機種で違う。テザリングだけでは WorkManager の CONNECTED 制約を満たさない見込み。PCのアドレスがテザリングのたびに変わるかも分からない | 実機で確かめる（下の実機確認）。アプリを開いている間は「PCに届くようになった」で送る |
| 古いPC（P2未導入） | `POST /inspections/.../manifest` と `GET /routes` が404 | 点検は送信待ちのまま、「PCのアプリを更新してください」と出す。写真は送られる |
| 点検の写真を従来の履歴から操作 | 従来の画面から削除・再送されると状態が食い違う | `LegacyQueueView` で従来の画面から見えなくする |

**実機確認の項目**（P6のPRで結果を書く）:
1. Wi-Fi: 作成 → 撮影3枚 → 完了 → 送信中 → 送信済み。PCの点検画面と一致する。
2. PCを止めて完了 → 送信待ち（Wi-Fiだが届かない）→ PCを起動 → アプリを開いたまま自動で送信される。
3. Wi-Fiを切ってUSBテザリング → 帯が「USBテザリング」→ PCのQRで登録し直す → 送信される。テザリングをやり直したときのPCのアドレス、網の名前（`rndis0` 等）を記録する。
4. 送信中にアプリを強制終了 → 再起動で送信が再開し、二重に保存されない。
5. 1枚の画像ファイルを消してから完了 → 送信済み（未到着1枚）になる。

---

## 11. PC側（P2）へ伝える事項

この設計で送るmanifest・サイドカーの細部。取り決めの範囲内だが、P2の実装で受けられるか確かめる。
- `operator`・`place`・`route_id`・各写真の `device_id`・`device_id_source`・`sha256` が `null` になることがある。
- ルートなしの点検は `missing: []`・`extra: []`。`route_id` が null なら未撮影を判定しない。
- `missing`・`extra` はスマホが作成時のルートのコピーで計算した値。PCは今のルートで計算し直さない。
- `missing_photos` は、受信口が `incoming/` に保存した画像と照合して返す（取り込みの完了を待たない）。待つと、届いた直後の写真が未着に数えられ、スマホが再送してしまう。
- 点検IDの形は `INS-20261106T003012Z-1a2b3c4d`（29文字）。
- 写真の `device_id_source` は `qr` か `manual` だけ（F18の既存の受け付けと同じ）。

---

## 12. 要確認（ユーザーに決めてもらう事項。既定値で実装を進める）

1. **従来の撮影画面（点検なし）を残すか。** 既定: 残す。ホームの下に小さく「点検なしで撮る（従来の画面）」を置く。評価用の撮影（真値の入力）と、点検に属さない古い写真の確認に使うため。消すなら P6 の後に別PRで外す。
2. **USBテザリングで送るときの登録の手間。** 既定: テザリング中にPCの「スマホを登録」のQRを一度読めば、以後はWi-FiとUSBを自動で切り替える（§4.3）。テザリングのたびにPCのアドレスが変わる機種では毎回の登録が要る。実機確認3の結果しだいで、PC側で固定のアドレスを使う方法などを別に考える。
3. **送信済みの点検の写真を端末から消す操作。** 既定: 初版では作らない（端末に残り続ける）。連日の現場利用の前に、保持期間か手動削除を決める（送信機構レビュー P1 と同じ課題）。

---

## 設計の要約

1. 点検は Room の `inspections` 表（version 4→5）で持ち、写真の `queue_items` に `inspectionId`・`inspectionName`・`routeId` を足す。旧写真は NULL のまま、今までどおり送る。
2. 状態は 作業中 → 送信待ち → 送信中 → 送信済み／送信済み（未到着N枚）。遷移は純粋関数で判定し、再開はできない。
3. 作業中の点検の写真は、HTTPにも送信箱にも出さない（`SendRouter` に既定値つきの `isSendable` を足す）。
4. 写真がすべて届くか端末で失敗が確定したら、manifest を `POST /inspections/<id>/manifest` で送る。PCの `missing_photos` と端末の失敗を合わせて「未到着N枚」とする。
5. 再送は失敗・未着の写真だけ、またはmanifestだけ。PCの重複判定とmanifestの上書きで冪等にする。
6. 「PCに届く」は既存の `/health`。接続の種類は Wi-Fi・有線（ConnectivityManager）とUSBテザリング（網の名前）で表示し、届くようになった時点で自動送信する。USB用に同じPCのURL候補を持つ。
7. 画面は ViewModel なしの既存の書き方で、新ファイル `ui/inspection/` に置く。表示は `XxxUiState` の純粋関数でテストする。
8. ルートは `GET /routes`・QR で受け取り `filesDir/routes.json` に保存し、点検の作成時にコピーする。
9. 既存ファイルの変更は既定値つきの引数・`private` → `internal`・中身を変えない切り出しに限り、既存テストの期待値を変えない。
10. 要確認は3点（従来画面を残すか、USBテザリングの登録の手間、送信済み写真の片付け）。
