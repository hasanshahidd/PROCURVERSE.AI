$j = Get-Content 'C:\Users\HP\.claude\projects\C--Users-HP-OneDrive-Documents-procure-AI\c5937ff2-8406-47ea-839c-7caa970da888\tool-results\toolu_01PanYyFuukzAYe8KzRti3s8.json' -Raw | ConvertFrom-Json
$j | ForEach-Object { Write-Output $_.text }
