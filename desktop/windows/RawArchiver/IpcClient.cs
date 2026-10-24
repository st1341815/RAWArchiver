using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;

namespace RawArchiver;

/// <summary>与核心引擎 CLI 的 IPC 客户端（NDJSON over stdin/stdout）。</summary>
public sealed class IpcClient
{
    public event Action<string, Dictionary<string, object>>? OnEvent;

    private Process? _process;
    private StreamWriter? _stdin;
    private int _nextId;
    private readonly Dictionary<int, TaskCompletionSource<Dictionary<string, object>>> _pending = new();

    public bool IsRunning => _process != null && !_process.HasExited;

    public static string? LocateCli(string varDir)
    {
        // 1) 环境变量（调试/排障）
        var env = Environment.GetEnvironmentVariable("RA_CLI");
        if (!string.IsNullOrEmpty(env) && File.Exists(env)) return env;
        // 2) 开发态：程序旁的 RawArchiver-cli/（PyInstaller onedir）
        var cli = Path.Combine(AppContext.BaseDirectory, "RawArchiver-cli", "RawArchiver-cli.exe");
        if (File.Exists(cli)) return cli;
        // 3) 单文件发布：内嵌资源释放到缓存目录
        return EnsureEmbeddedCli(varDir);
    }

    /// <summary>把内嵌的 Python CLI（单文件 exe）释放到缓存目录，返回路径。</summary>
    private static string? EnsureEmbeddedCli(string varDir)
    {
        var asm = typeof(IpcClient).Assembly;
        var name = asm.GetManifestResourceNames()
            .FirstOrDefault(n => n.EndsWith("RawArchiver-cli.exe", StringComparison.OrdinalIgnoreCase));
        if (name == null) return null;

        var ver = asm.GetName().Version?.ToString() ?? "0";
        var dir = Path.Combine(varDir, "cli", ver);
        var exe = Path.Combine(dir, "RawArchiver-cli.exe");
        try
        {
            if (File.Exists(exe) && new FileInfo(exe).Length > 1024 * 1024) return exe;
            Directory.CreateDirectory(dir);
            using var s = asm.GetManifestResourceStream(name);
            if (s == null) return null;
            var tmp = exe + ".tmp";
            using (var f = File.Create(tmp)) s.CopyTo(f);
            if (File.Exists(exe)) File.Delete(exe);
            File.Move(tmp, exe);
            return exe;
        }
        catch
        {
            return null;
        }
    }

    public void Launch(string cliPath, string varDir)
    {
        Stop();
        var psi = new ProcessStartInfo
        {
            FileName = cliPath,
            Arguments = "--ipc",
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = Encoding.UTF8,
        };
        psi.Environment["TRIM_PKGVAR"] = varDir;
        psi.Environment["PYTHONIOENCODING"] = "utf-8";

        var p = Process.Start(psi);
        if (p == null) return;
        _process = p;
        _stdin = p.StandardInput;
        _nextId = 0;
        _pending.Clear();

        p.OutputDataReceived += (_, e) =>
        {
            if (e.Data != null) HandleLine(e.Data);
        };
        p.ErrorDataReceived += (_, _) => { };
        p.BeginOutputReadLine();
        p.BeginErrorReadLine();
    }

    public Task<Dictionary<string, object>> Request(string cmd, Dictionary<string, object>? payload = null)
    {
        var tcs = new TaskCompletionSource<Dictionary<string, object>>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        if (!IsRunning || _stdin == null)
        {
            tcs.SetException(new InvalidOperationException("核心服务未运行"));
            return tcs.Task;
        }
        var id = ++_nextId;
        _pending[id] = tcs;
        var obj = payload ?? new Dictionary<string, object>();
        obj["id"] = id;
        obj["cmd"] = cmd;
        try
        {
            _stdin.WriteLine(JsonSerializer.Serialize(obj));
            _stdin.Flush();
        }
        catch (Exception ex)
        {
            _pending.Remove(id);
            tcs.SetException(ex);
        }
        return tcs.Task;
    }

    public void Stop()
    {
        try
        {
            _stdin?.WriteLine("{\"id\":999999,\"cmd\":\"shutdown\"}");
            _stdin?.Flush();
        }
        catch { }
        try { _process?.Kill(); } catch { }
        _process = null;
        _stdin = null;
    }

    private void HandleLine(string line)
    {
        if (string.IsNullOrWhiteSpace(line)) return;
        try
        {
            using var doc = JsonDocument.Parse(line);
            var root = doc.RootElement;
            if (root.TryGetProperty("id", out var idProp) && !root.TryGetProperty("evt", out _))
            {
                int id = idProp.GetInt32();
                if (_pending.Remove(id, out var tcs))
                {
                    tcs.SetResult(Convert.ToDict(root));
                }
            }
            else if (root.TryGetProperty("evt", out var evtProp))
            {
                OnEvent?.Invoke(evtProp.GetString() ?? "", Convert.ToDict(root));
            }
        }
        catch { }
    }
}

/// <summary>JsonElement → object 转换辅助。</summary>
public static class Convert
{
    public static Dictionary<string, object> ToDict(JsonElement el)
    {
        var d = new Dictionary<string, object>();
        if (el.ValueKind != JsonValueKind.Object) return d;
        foreach (var p in el.EnumerateObject())
        {
            d[p.Name] = Value(p.Value)!;
        }
        return d;
    }

    public static object? Value(JsonElement el)
    {
        switch (el.ValueKind)
        {
            case JsonValueKind.Object: return ToDict(el);
            case JsonValueKind.Array: return el.EnumerateArray().Select(Value).ToList();
            case JsonValueKind.String: return el.GetString();
            case JsonValueKind.Number:
                if (el.TryGetInt64(out var l)) return l;
                return el.GetDouble();
            case JsonValueKind.True: return true;
            case JsonValueKind.False: return false;
            default: return null;
        }
    }

    public static string Str(object? o) => o?.ToString() ?? "";

    public static long Long(object? o) => o is long l ? l : (o is int i ? i : 0);

    public static bool Bool(object? o) => o is bool b && b;

    public static List<Dictionary<string, object>> DictList(object? o)
        => o is List<object?> list
            ? list.Select(x => x is Dictionary<string, object> d ? d : new Dictionary<string, object>()).ToList()
            : new List<Dictionary<string, object>>();
}
