Add-Type -AssemblyName System.Net
$root = "C:\Users\Flareium\.gemini\antigravity\scratch\calculater"
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:8787/")
$listener.Start()
"Server started on http://localhost:8787/" | Out-File "C:\Users\Flareium\.gemini\antigravity\scratch\calculater\server.log" -Append
while ($true) {
  try {
    $ctx = $listener.GetContext()
    $req = $ctx.Request
    $res = $ctx.Response
    $urlPath = $req.Url.LocalPath.TrimStart("/")
    if ($urlPath -eq "") { $urlPath = "index.html" }
    $filePath = Join-Path $root $urlPath
    if (Test-Path $filePath -PathType Leaf) {
      $ext = [System.IO.Path]::GetExtension($filePath)
      $mime = switch ($ext) { ".html"{"text/html; charset=utf-8"} ".css"{"text/css"} ".js"{"application/javascript"} default{"application/octet-stream"} }
      $bytes = [System.IO.File]::ReadAllBytes($filePath)
      $res.ContentType = $mime
      $res.ContentLength64 = $bytes.Length
      $res.OutputStream.Write($bytes, 0, $bytes.Length)
    } else {
      $res.StatusCode = 404
      $b = [System.Text.Encoding]::UTF8.GetBytes("Not Found")
      $res.OutputStream.Write($b, 0, $b.Length)
    }
    $res.OutputStream.Close()
  } catch {}
}
