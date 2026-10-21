using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Threading.Tasks;

namespace Cap2ModManager
{
    /// <summary>cap2mod.py 실행기. 적용·복원·동기화 같은 실제 작업은 모두 cap2mod.py가 한다.</summary>
    internal sealed class Cap2Py
    {
        public string ScriptPath { get; }
        public string PythonExe { get; private set; }
        public string PythonPrefixArgs { get; private set; } = "";
        public string PythonLabel => PythonExe == null ? "(없음)" : (PythonExe + " " + PythonPrefixArgs).Trim();

        public Cap2Py(string scriptPath) { ScriptPath = scriptPath; }

        /// <summary>exe 옆(또는 상위 폴더)의 cap2mod.py 찾기</summary>
        public static string FindScript()
        {
            var dir = AppDomain.CurrentDomain.BaseDirectory;
            for (int k = 0; k < 4 && dir != null; k++)
            {
                var p = Path.Combine(dir, "cap2mod.py");
                if (File.Exists(p)) return p;
                dir = Path.GetDirectoryName(dir.TrimEnd('\\'));
            }
            return null;
        }

        /// <summary>실제로 동작하는 Python 3.8+ 찾기 (일부 설치본은 표준 라이브러리가 깨져 있음)</summary>
        public bool DetectPython()
        {
            var cands = new List<(string exe, string pre)>();
            foreach (var v in new[] { "3", "3.13", "3.12", "3.11", "3.10", "3.9", "3.8" }) cands.Add(("py", "-" + v));
            cands.Add(("python", ""));
            const string test = "import sys, json, hashlib, zipfile; assert sys.version_info >= (3, 8); print(sys.executable)";
            string fallback = null;
            foreach (var (exe, pre) in cands)
            {
                try
                {
                    var r = RunSync(exe, (pre + " -c \"" + test + "\"").Trim(), 15000);
                    if (r.code != 0 || r.stdout.Trim().Length == 0) continue;
                    // py 런처 대신 실제 python.exe 경로를 직접 사용(경고 출력·시작 지연 감소)
                    var path = r.stdout.Trim().Split('\n')[0].Trim();
                    // 표준 라이브러리 경로가 깨진 설치본(경고 출력)은 다른 후보가 없을 때만 사용
                    if (r.stderr.Contains("Could not find platform")) { fallback = fallback ?? path; continue; }
                    PythonExe = path;
                    return true;
                }
                catch (Exception) { }
            }
            if (fallback != null) { PythonExe = fallback; return true; }
            PythonExe = null;
            return false;
        }

        static (int code, string stdout, string stderr) RunSync(string exe, string args, int timeoutMs)
        {
            var psi = new ProcessStartInfo(exe, args)
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
            };
            using (var p = Process.Start(psi))
            {
                var o = p.StandardOutput.ReadToEndAsync();
                var e = p.StandardError.ReadToEndAsync();
                if (!p.WaitForExit(timeoutMs)) { try { p.Kill(); } catch { } return (-1, "", ""); }
                p.WaitForExit();
                return (p.ExitCode, o.Result, e.Result);
            }
        }

        static string Quote(string a)
        {
            if (a.Length > 0 && a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0) return a;
            var t = a.Replace("\"", "\\\"");
            if (t.EndsWith("\\")) t += "\\";          // 닫는 따옴표 앞 역슬래시가 따옴표를 이스케이프하지 않게
            return "\"" + t + "\"";
        }

        /// <summary>cap2mod.py 실행. 출력 줄마다 onLine 호출. 종료 코드와 전체 표준 출력을 돌려준다.</summary>
        public Task<(int code, string stdout)> RunAsync(IEnumerable<string> args, Action<string> onLine)
        {
            var sb = new StringBuilder();
            foreach (var a in args) sb.Append(' ').Append(Quote(a));
            var psi = new ProcessStartInfo(PythonExe, (PythonPrefixArgs + " " + Quote(ScriptPath) + sb).Trim())
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8,
                WorkingDirectory = Path.GetDirectoryName(ScriptPath),
            };
            psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            psi.EnvironmentVariables["PYTHONUTF8"] = "1";
            var tcs = new TaskCompletionSource<(int, string)>();
            var all = new StringBuilder();
            var p = new Process { StartInfo = psi, EnableRaisingEvents = true };
            int open = 2;
            void Done()
            {
                // 출력 콜백 안에서 WaitForExit()을 부르면 콜백 종료를 기다리며 교착되므로 다른 스레드에서 기다린다
                if (System.Threading.Interlocked.Decrement(ref open) == 0)
                    Task.Run(() =>
                    {
                        p.WaitForExit();
                        tcs.TrySetResult((p.ExitCode, all.ToString()));
                        p.Dispose();
                    });
            }
            p.OutputDataReceived += (s, e) => { if (e.Data == null) { Done(); return; } lock (all) all.AppendLine(e.Data); onLine?.Invoke(e.Data); };
            p.ErrorDataReceived += (s, e) => { if (e.Data == null) { Done(); return; } if (!e.Data.StartsWith("Could not find platform")) onLine?.Invoke(e.Data); };
            p.Start();
            p.BeginOutputReadLine();
            p.BeginErrorReadLine();
            return tcs.Task;
        }
    }
}
