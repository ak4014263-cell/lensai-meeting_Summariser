param([string]$OutFile = "$PSScriptRoot\meeting_speech.wav")

Add-Type -AssemblyName System.Speech

$script = @"
Alright, let's start the sprint planning meeting. First item, the payment gateway migration.
We agreed to move the payment gateway to Stripe by the end of this quarter.
Priya will prepare the production build and have it ready by Friday.
There is a risk that the load testing environment is not ready in time, which could delay the release.
Second item, the mobile application login bug. Rahul will fix the login bug and deploy the patch on Wednesday.
One open question remains. Do we need a separate staging database for the migration? We will decide that next week.
The decision is confirmed. We ship the beta release on the twentieth of March.
That is everything for today. Thank you all for joining.
"@

$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile($OutFile, $fmt)
$synth.Rate = 0
$synth.Speak($script)
$synth.Dispose()

$info = Get-Item $OutFile
Write-Output "WROTE $($info.FullName) $($info.Length) bytes"
