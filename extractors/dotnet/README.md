# dotnet extractor(骨架)

Roslyn extractor 尚未實作,見 `docs/HANDOFF.md` §6.2。Mac 上一律用 Docker 跑 dotnet,不裝本機 SDK。

- Build: `docker run --rm -v "$PWD":/src -w /src mcr.microsoft.com/dotnet/sdk:9.0 dotnet build`
- Test: `docker run --rm -v "$PWD":/src -w /src mcr.microsoft.com/dotnet/sdk:9.0 dotnet test`
