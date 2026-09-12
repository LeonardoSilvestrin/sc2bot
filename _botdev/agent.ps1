# Abre/reseta a worktree de um agente no ultimo commit da branch atual da pasta principal.
# Uso: .\_botdev\agent.ps1 claude   |   .\_botdev\agent.ps1 codex -NoOpen
param(
    [Parameter(Mandatory = $true)][string]$Name,
    [switch]$NoOpen
)

function Invoke-Git {
    & git @args
    if ($LASTEXITCODE -ne 0) { throw "falhou: git $($args -join ' ')" }
}

$prevEncoding = [Console]::OutputEncoding
[Console]::OutputEncoding = [Text.Encoding]::UTF8
try {
    $main = (git -C $PSScriptRoot worktree list --porcelain | Select-Object -First 1) -replace '^worktree ', ''
    $main = $main -replace '/', '\'
    $base = git -C $main branch --show-current
    if (-not $base) { throw "pasta principal ($main) esta em detached HEAD" }
    $commit = (git -C $main rev-parse --short HEAD)
    $branch = "agents/$Name"
    $path = Join-Path (Split-Path $main -Parent) ("{0}.worktrees\{1}" -f (Split-Path $main -Leaf), $Name)

    Invoke-Git -C $main worktree prune

    $registered = git -C $main worktree list --porcelain |
        Where-Object { $_ -like 'worktree *' } |
        ForEach-Object { ($_ -replace '^worktree ', '') -replace '/', '\' }

    if ((Test-Path $path) -and -not ($registered -contains $path)) {
        throw "$path existe mas nao e worktree desse repo. Apaga: Remove-Item -Recurse -Force '$path'"
    }

    $lost = git -C $main log --oneline "$commit..$branch" 2>$null
    if ($lost) {
        $old = git -C $main rev-parse --short $branch
        Write-Warning "$branch tinha commits fora de $base, descartados (recuperar: git branch resgate $old):"
        $lost | ForEach-Object { Write-Host "  $_" }
    }

    if ($registered -contains $path) {
        Invoke-Git -C $path checkout -q -f -B $branch $commit
        Invoke-Git -C $path clean -q -fdx -e .venv
    } else {
        Invoke-Git -C $main worktree add -q -f -B $branch $path $commit
    }
    Invoke-Git -C $path submodule update -q --init --recursive --force

    Write-Host "$Name -> $branch @ $commit ($base)  $path" -ForegroundColor Green
    if (-not $NoOpen) { code -n $path }
} finally {
    [Console]::OutputEncoding = $prevEncoding
}
