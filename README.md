# qr-based-sport-analyzer



```
Get-ChildItem -Filter *.mp4 | ForEach-Object {
    $file = $_.FullName
    Write-Host "`n$file"
    & "C:\Program Files\ffmpeg\bin\ffprobe.exe" -v error -select_streams v:0 -count_packets -show_entries stream=nb_read_packets -of csv=p=0 "$file"
}


```
