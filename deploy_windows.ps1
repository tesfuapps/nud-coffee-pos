# ================================================================
#  NUD COFFEE BOT — Windows Deploy Script (PowerShell)
#  Run this from YOUR Windows PC after creating the Oracle VM
# ================================================================
#
#  HOW TO USE:
#    1. Open PowerShell
#    2. Navigate to this folder:
#       cd "c:\Users\OLY-104\Desktop\Nud coffee\Nud coffee"
#    3. Run:
#       .\deploy_windows.ps1 -VMIp "YOUR_VM_IP" -KeyPath "C:\path\to\your\key.key"
# ================================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$VMIp,

    [Parameter(Mandatory=$true)]
    [string]$KeyPath
)

$BOT_DIR  = "c:\Users\OLY-104\Desktop\Nud coffee\Nud coffee"
$VM_USER  = "ubuntu"
$REMOTE   = "$VM_USER@$VMIp"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║   NUD COFFEE BOT — DEPLOYING TO ORACLE VM   ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# --- Step 1: Create remote directory ---
Write-Host "📁 Step 1/3: Creating project folder on VM..." -ForegroundColor Yellow
ssh -i "$KeyPath" -o StrictHostKeyChecking=no $REMOTE "mkdir -p ~/nud_coffee"

# --- Step 2: Upload all bot files ---
Write-Host ""
Write-Host "📤 Step 2/3: Uploading bot files..." -ForegroundColor Yellow
$files = @("bot.py", "database.py", "config.py", "requirements.txt", ".env", "deploy_setup.sh")
foreach ($file in $files) {
    $local = Join-Path $BOT_DIR $file
    if (Test-Path $local) {
        scp -i "$KeyPath" -o StrictHostKeyChecking=no "$local" "${REMOTE}:~/nud_coffee/"
        Write-Host "  ✅ Uploaded: $file" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️  Skipped (not found): $file" -ForegroundColor DarkYellow
    }
}

# --- Step 3: Run setup script on VM ---
Write-Host ""
Write-Host "🚀 Step 3/3: Running auto-setup on VM..." -ForegroundColor Yellow
ssh -i "$KeyPath" -o StrictHostKeyChecking=no $REMOTE "chmod +x ~/nud_coffee/deploy_setup.sh && bash ~/nud_coffee/deploy_setup.sh"

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "║  ✅ DEPLOYMENT COMPLETE! Bot is live on Oracle VM   ║" -ForegroundColor Green
Write-Host "╚══════════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "🔎 To view live logs, run:" -ForegroundColor Cyan
Write-Host "   ssh -i `"$KeyPath`" $REMOTE `"sudo journalctl -u nudcoffee -f`"" -ForegroundColor White
Write-Host ""
Write-Host "🔁 To update the bot later, just re-run this script!" -ForegroundColor Cyan
Write-Host ""
