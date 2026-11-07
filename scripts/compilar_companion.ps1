# Compila la app JARVIS para Android (companion/) sin Android Studio ni Gradle.
# Necesita: Java 17 y el SDK de Android con "platforms;android-34" y "build-tools;34.0.0".
# Uso (desde la carpeta de JARVIS):  powershell -ExecutionPolicy Bypass -File scripts\compilar_companion.ps1
# Resultado: build\companion\JARVIS.apk
$ErrorActionPreference = "Stop"
$raiz = Split-Path -Parent $PSScriptRoot
$sdk = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { "$env:LOCALAPPDATA\Android\Sdk" }
$bt = Get-ChildItem "$sdk\build-tools" -Directory | Sort-Object Name -Descending | Select-Object -First 1 -ExpandProperty FullName
$androidJar = Get-ChildItem "$sdk\platforms" -Directory | Sort-Object Name -Descending | Select-Object -First 1 | ForEach-Object { "$($_.FullName)\android.jar" }
$jdk = if ($env:JAVA_HOME) { $env:JAVA_HOME } else { Get-ChildItem "$env:ProgramFiles\Microsoft" -Directory | Where-Object Name -match '^jdk-17' | Select-Object -First 1 -ExpandProperty FullName }
$env:JAVA_HOME = $jdk
$env:PATH = "$jdk\bin;$env:PATH"
$out = "$raiz\build\companion"
$fuente = "$raiz\companion"
# La firma de la app se guarda fuera del repositorio (no se sube a GitHub)
$almacen = "$env:USERPROFILE\.jarvis\companion-firma.jks"

if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force "$out\gen", "$out\clases", "$out\dex" | Out-Null

Write-Host "1/6 Recursos"
& "$bt\aapt2.exe" compile --dir "$fuente\res" -o "$out\res.zip"; if ($LASTEXITCODE) { throw "aapt2 compile" }
& "$bt\aapt2.exe" link -I $androidJar --manifest "$fuente\AndroidManifest.xml" -o "$out\base.apk" "$out\res.zip" --java "$out\gen" --min-sdk-version 26 --target-sdk-version 34
if ($LASTEXITCODE) { throw "aapt2 link" }

Write-Host "2/6 Java"
$javas = @(Get-ChildItem "$fuente\src", "$out\gen" -Recurse -Filter *.java | ForEach-Object FullName)
& "$jdk\bin\javac.exe" --release 11 -encoding UTF-8 -classpath $androidJar -d "$out\clases" @javas
if ($LASTEXITCODE) { throw "javac" }

Write-Host "3/6 DEX"
$clases = @(Get-ChildItem "$out\clases" -Recurse -Filter *.class | ForEach-Object FullName)
& "$bt\d8.bat" --release --min-api 26 --lib $androidJar --output "$out\dex" @clases
if ($LASTEXITCODE) { throw "d8" }

Write-Host "4/6 Empaquetar"
Copy-Item "$out\base.apk" "$out\sin-firmar.apk"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open("$out\sin-firmar.apk", "Update")
[System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, "$out\dex\classes.dex", "classes.dex") | Out-Null
$zip.Dispose()
& "$bt\zipalign.exe" -f -p 4 "$out\sin-firmar.apk" "$out\alineado.apk"; if ($LASTEXITCODE) { throw "zipalign" }

Write-Host "5/6 Firma"
if (-not (Test-Path $almacen)) {
    New-Item -ItemType Directory -Force (Split-Path $almacen) | Out-Null
    $clave = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    Set-Content -Path "$almacen.clave" -Value $clave -NoNewline -Encoding ascii
    & "$jdk\bin\keytool.exe" -genkeypair -keystore $almacen -alias jarvis -keyalg RSA -keysize 2048 -validity 10000 `
        -storepass $clave -keypass $clave -dname "CN=JARVIS, O=Potro" | Out-Null
}
$clave = Get-Content "$almacen.clave" -Raw
& "$bt\apksigner.bat" sign --ks $almacen --ks-key-alias jarvis --ks-pass "pass:$clave" --key-pass "pass:$clave" `
    --out "$out\JARVIS.apk" "$out\alineado.apk"
if ($LASTEXITCODE) { throw "apksigner" }

Write-Host "6/6 Comprobación"
& "$bt\apksigner.bat" verify "$out\JARVIS.apk"; if ($LASTEXITCODE) { throw "verify" }
Write-Host "Listo: $out\JARVIS.apk ($([math]::Round((Get-Item "$out\JARVIS.apk").Length/1KB)) KB)"
