# PostgreSQL Local Backup Manual Runbook and CLI Decision Record

## 1. Task 6.4.5 Decision Record

- **Status:** **NOT IMPLEMENTED BY DESIGN / MANUAL POWERSHELL-RUNBOOK ONLY**
- **Decision Date:** July 2026

### Rationale
During the security and feasibility audit for Task 6.4.5, the team evaluated automating the local PostgreSQL database backup through a new Flask CLI command (`flask ops backup-local-postgres`) running `docker exec spamanager-postgres pg_dump` under the hood.

A controlled, auth-only local PostgreSQL smoke test was conducted to verify if password-free connection using the container's default administrative privileges was possible:
- **Executed Command (Historical Evidence):**
  ```bash
  docker exec --user postgres spamanager-postgres \
    pg_dump --schema-only --format=custom \
    --dbname=spamanager_dev --username=postgres \
    --no-password --file=/dev/null
  ```
- **Result:** Completed with exit code `1`.
- **Error Output:** `FATAL: role "postgres" does not exist`

This historical evidence specifically refutes the exact command contract that attempts to connect using the database role `postgres` without a password. It does not prove that the local cluster was initialized with a specific database role. The project actively chose not to continue database role discovery or automate password handling in application code. The team does not conclude that all password-free configurations are impossible, but rather that manual credential management outside of the application code has a significantly lower security exposure.

Consequently, the Owner and Reviewer decided **not to implement any automated Flask CLI backup commands or Web UI backup actions**. Instead, all local PostgreSQL backups will be managed manually by the developer/operator using external command line tools, with credentials managed entirely outside of the repository code.

---

## 2. Scope

- **Applicability:** Local Docker PostgreSQL development environment only.
- **Non-applicability:** Does not apply to Railway production PostgreSQL (which is strictly managed at the infrastructure provider level).
- **Application Boundary:** This process is completely external to the SpaManager Web Application and does not involve any Flask CLI commands, web routes, or templates. No new buttons or actions will be added to the Backup Center UI.
- **Responsibility:** The local developer/operator is solely responsible for managing local credentials and ensuring the safe storage of backup files.

---

## 3. Local Environment Checkpoints

- **Docker Container Name:** `spamanager-postgres`
- **Host Endpoint:** `localhost:5433` (forwarding to container port `5432`)
- **Development Database Name:** `spamanager_dev`
- **Database User:** Provided dynamically by the operator via PowerShell interaction. No database username is recorded as a project default.
- **SQLite Fallback:** SQLite is strictly used as a legacy or unit-test fallback and is not the product runtime.

---

## 4. Tooling and Version Preflight

- **Host Environment:** The local Windows host does not have `pg_dump` or PostgreSQL client utilities installed in the environment PATH by default.
- **Container Environment:** The `postgres:16` Docker container includes `pg_dump` version `16.14`.
- **Version Compatibility:** Container recreation may change the underlying minor version of PostgreSQL. The operator must run the version preflight check before performing a manual backup:
  ```bash
  docker exec spamanager-postgres pg_dump --version
  ```
  Ensure the command succeeds and outputs a version compatible with PostgreSQL 16.

---

## 5. Manual Backup Runbook

### Security and Storage Principles
1. **Credential Isolation:** Credentials must be managed entirely outside the Git repository. Do not write plain passwords or raw connection strings (`DATABASE_URL`) in command history, scripts, or documentation.
2. **Interactive Password Prompt:** The manual runbook is designed to let `pg_dump` prompt for the password interactively inside the container terminal if the local PostgreSQL authentication configuration requires it. If local auth does not require a password, the command will proceed without prompting. Runbook commands do not pass the password in environment variables (like `PGPASSWORD`), arguments, or files, and do not write them in command logs or history.
3. **Storage Location:** All backup files must be saved outside the repository workspace and completely outside the `static/` folder or any web-accessible directory. Do not use folders inside the repository even if they are in `.gitignore`.
4. **Format Policy:** Backups must be generated in PostgreSQL Custom Format (`-Fc` or `--format=custom`), which yields a compressed binary dump.
5. **Data Sensitivity:** Custom-format `.dump` files are compressed but **not encrypted**. They contain full schema and business data, and must be treated as highly sensitive assets.
6. **No Overwrite:** Filenames must be collision-safe and use UTC timestamps. Never overwrite existing files.

### Binary-Safe Backup Flow
To prevent corrupting the binary data, the custom-format dump must not be piped through Windows PowerShell or standard redirections (`>`). Instead, the backup file is written to a temporary path inside the container and then copied to the host using `docker cp`.

The following unified PowerShell script executes the local backup flow safely:

```powershell
$ErrorActionPreference = "Stop"

# 1. Setup paths (Modify this example path for your local workspace)
$BackupDir = "C:\Users\ADMIN\SpaManagerBackups"
if ([string]::IsNullOrWhiteSpace($BackupDir)) {
    throw "Backup directory path cannot be empty."
}

if (-not [System.IO.Path]::IsPathRooted($BackupDir)) {
    throw "Backup directory must be an absolute path."
}

$ResolvedBackupDir = [System.IO.Path]::GetFullPath($BackupDir)

$RepoRootRaw = git rev-parse --show-toplevel 2>$null
$GitExitCode = $LASTEXITCODE

if ($GitExitCode -ne 0 -or
    [string]::IsNullOrWhiteSpace($RepoRootRaw)) {
    throw "Run this procedure from inside the SpaManager Git repository."
}

$RepoRoot = [System.IO.Path]::GetFullPath(
    ($RepoRootRaw | Select-Object -First 1).Trim()
)

$StaticRoot = [System.IO.Path]::GetFullPath(
    (Join-Path $RepoRoot "static")
)

# Path containment helper avoiding prefix bugs
$Sep = [System.IO.Path]::DirectorySeparatorChar.ToString()
$NormalizedBackup = $ResolvedBackupDir.TrimEnd($Sep) + $Sep
$NormalizedRepo = $RepoRoot.TrimEnd($Sep) + $Sep
$NormalizedStatic = $StaticRoot.TrimEnd($Sep) + $Sep

if ($NormalizedBackup.StartsWith($NormalizedRepo, [System.StringComparison]::OrdinalIgnoreCase) -or 
    $NormalizedBackup.StartsWith($NormalizedStatic, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Backup directory cannot reside inside the repository or static root."
}

# Ensure directory exists or let operator create it
if (-not (Test-Path -LiteralPath $ResolvedBackupDir)) {
    throw "Backup directory does not exist. Please create it first: $ResolvedBackupDir"
}

$BackupDirItem = Get-Item -LiteralPath $ResolvedBackupDir

if (-not $BackupDirItem.PSIsContainer) {
    throw "Backup path must be a directory."
}

if (($BackupDirItem.Attributes -band
     [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
    throw "Backup directory cannot be a symbolic link or junction."
}

# 2. Get local database username interactively (does not read password)
$LocalDbUser = Read-Host "Local PostgreSQL user"
if ([string]::IsNullOrWhiteSpace($LocalDbUser)) {
    throw "Database user cannot be empty."
}

# 3. Generate safe timestamps and unique tokens
$Stamp = [DateTime]::UtcNow.ToString("yyyyMMdd_HHmmss_fff")
$Token = [Guid]::NewGuid().ToString("N").Substring(0, 8)

$BaseName = "local_backup_${Stamp}_${Token}"
$BackupFile = "$BaseName.dump"
$PartialFile = "$BaseName.dump.partial"

$HostPartialPath = Join-Path $ResolvedBackupDir $PartialFile
$HostFinalPath = Join-Path $ResolvedBackupDir $BackupFile
$ContainerTempPath = "/tmp/$BackupFile"

if (Test-Path -LiteralPath $HostPartialPath) { throw "Host partial file already exists." }
if (Test-Path -LiteralPath $HostFinalPath) { throw "Host final file already exists." }

$BackupSuccess = $false
try {
    # 4. Execute backup in interactive mode
    # Operator will be prompted for database password interactively by pg_dump inside the terminal
    docker exec -it spamanager-postgres `
      pg_dump `
      --host=127.0.0.1 `
      --port=5432 `
      --username=$LocalDbUser `
      --dbname=spamanager_dev `
      --format=custom `
      --file=$ContainerTempPath

    $DumpExitCode = $LASTEXITCODE
    if ($DumpExitCode -ne 0) {
        throw "pg_dump failed with exit code $DumpExitCode"
    }

    # 5. Copy file from container to host
    docker cp `
      "spamanager-postgres:$ContainerTempPath" `
      "$HostPartialPath"

    $CopyExitCode = $LASTEXITCODE
    if ($CopyExitCode -ne 0) {
        throw "docker cp failed with exit code $CopyExitCode"
    }

    # 6. Verify and finalize without using -Force (prevent overwrite)
    if (-not (Test-Path -LiteralPath $HostPartialPath)) {
        throw "Partial backup file was not successfully copied to host."
    }
    if ((Get-Item -LiteralPath $HostPartialPath).Length -eq 0) {
        throw "Partial backup file size is 0 bytes."
    }
    if (Test-Path -LiteralPath $HostFinalPath) {
        throw "Host final file path already exists before rename."
    }

    Rename-Item `
      -LiteralPath $HostPartialPath `
      -NewName $BackupFile

    if (-not (Test-Path -LiteralPath $HostFinalPath)) {
        throw "Final backup file was not found after rename."
    }
    if ((Get-Item -LiteralPath $HostFinalPath).Length -eq 0) {
        throw "Final backup file size is 0 bytes."
    }
    if (Test-Path -LiteralPath $HostPartialPath) {
        throw "Partial backup file still exists after rename."
    }

    $BackupSuccess = $true
    Write-Host "Backup created successfully at: $HostFinalPath"

} finally {
    try {
        docker exec spamanager-postgres `
          rm -f -- $ContainerTempPath 2>&1 | Out-Null

        $CleanupExitCode = $LASTEXITCODE

        if ($CleanupExitCode -ne 0) {
            Write-Warning `
              "Container temporary file cleanup did not complete."
        }
    } catch {
        Write-Warning `
          "Container temporary file cleanup could not be executed."
    }

    try {
        if (-not $BackupSuccess -and
            (Test-Path -LiteralPath $HostPartialPath)) {
            Remove-Item -LiteralPath $HostPartialPath
        }
    } catch {
        Write-Warning `
          "Host partial file cleanup did not complete."
    }
}
```

*Note: If the container is stopped during execution, the cleanup in `finally` may fail to delete the container's temporary file. In such cases, the operator must manually inspect the `/tmp` directory of the container during the next startup to clean up leftover files.*

---

## 6. Local Restore Policy

- **No Active Restore:** Database restoration features are not part of Task 6.4.5c.
- **No Direct Restore:** Never attempt to restore a backup directly into the active development database `spamanager_dev`.
- **Controlled Rehearsal Only:** Any database restoration must be executed as a separate, controlled local rehearsal into a temporary database.
- **Explicit Approval Required:** Local restoration requires explicit approval because creating/deleting temporary databases is a database mutation.
- **No Web Restore:** Restoring database from the Web UI is completely disabled in PostgreSQL mode.
- **Production Restore:** Production database restoration is always an external, provider/runbook-managed operation requiring owner approval.
- **Testing Status:** This document does not verify that restore has been smoke-tested or validated for General Availability.
