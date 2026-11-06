package jp.sotuken.metercapture.route

const val ROUTE_QR_PREFIX = "SOTUKEN-ROUTE:"
sealed interface RouteQrResult {
    data class Ok(val route: RouteDoc) : RouteQrResult
    data class Error(val message: String) : RouteQrResult
}

fun parseRouteQr(raw: String): RouteQrResult {
    if (!raw.startsWith(ROUTE_QR_PREFIX)) return RouteQrResult.Error("ルートのQRではありません")
    if (raw.toByteArray(Charsets.UTF_8).size > 2048) return RouteQrResult.Error("ルートのQRが大きすぎます。PCから取得してください")
    return parseRouteJson(raw.removePrefix(ROUTE_QR_PREFIX))?.let { RouteQrResult.Ok(it) }
        ?: RouteQrResult.Error("ルートの内容が正しくありません")
}
