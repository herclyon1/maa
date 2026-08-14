# Push an image to WeCom (Enterprise WeChat) self-built app.
# Credentials come from environment variables - never hardcode them.
#   WECOM_CORPID / WECOM_SECRET / WECOM_AGENTID
# NOTE: the calling machine's public IP must be in the app's trusted-IP list,
#       otherwise the API returns errcode=60020.
param([Parameter(Mandatory=$true)][string]$Img)

$corp   = $env:WECOM_CORPID
$secret = $env:WECOM_SECRET
$agent  = $env:WECOM_AGENTID
if (-not $corp -or -not $secret -or -not $agent) {
  Write-Error "Set WECOM_CORPID / WECOM_SECRET / WECOM_AGENTID first."; exit 1
}
if (-not (Test-Path $Img)) { Write-Error "No such file: $Img"; exit 1 }

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$t = Invoke-RestMethod "https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=$corp&corpsecret=$secret"
if ($t.errcode -ne 0) { Write-Error ("gettoken failed: " + $t.errcode + " " + $t.errmsg); exit 1 }
$tok = $t.access_token

# curl.exe ships with Windows 10+ and handles multipart cleanly
$up = (& curl.exe -s -F "media=@$Img" `
      "https://qyapi.weixin.qq.com/cgi-bin/media/upload?access_token=$tok&type=image") | ConvertFrom-Json
if ($up.errcode -ne 0) { Write-Error ("upload failed: " + $up.errcode + " " + $up.errmsg); exit 1 }

$json = @{ touser="@all"; msgtype="image"; agentid=$agent; image=@{ media_id=$up.media_id } } |
        ConvertTo-Json -Depth 5 -Compress
$r = Invoke-RestMethod -Method Post `
     -Uri "https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=$tok" `
     -Body ([Text.Encoding]::UTF8.GetBytes($json)) -ContentType "application/json"
Write-Output ("errcode=" + $r.errcode + " " + $r.errmsg)
