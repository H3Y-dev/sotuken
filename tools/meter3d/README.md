# 3Dメーター生成器

Windows、Node.js 22以降、Google Chromeが必要です。npmパッケージは不要です。実行時にThree.js r128を https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js から取得するため、ネット接続が必要です。

Chromeが既定の場所にない場合はPowerShellで設定します。

```powershell
$env:CHROME_PATH = 'C:\path\to\chrome.exe'
```

リポジトリ直下から作業用コピーを作り、生成します。

```powershell
New-Item -ItemType Directory -Force demo | Out-Null
Copy-Item tools/meter3d demo/smoke-renderer -Recurse
node demo/smoke-renderer/batch/generate.cjs --meters pressure-1.6 --values 7 --cameras 0:0 --lightings normal --seed 1011 --out demo/smoke
```

外部生成器の `DESIGN.md` と `batch/README.md` を参照しました。取り込み元のSHA-256:

- `meter3d.html`: `c3b6f7c5551be1c36dddd84f2483fb1c96a6239cd0c33946fcc96274484da731`
- `batch/generate.cjs`: `f90ccfb9105f7054da3f1fae6e929dfdd3cb5a1477b444e41dba25b2183d7ad4`
- `batch/final_set_plan.cjs`: `f5db7a3f45475ae69661d8673e6f5f426f54d0f9df3cc4cbd56a7f1fa6ea8d69`
