using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace Cap2ModManager
{
    /// <summary>Capitalism 2 모드 매니저 Windows 화면. 작업은 cap2mod.py에 맡기고 결과를 보여 준다.</summary>
    internal sealed class MainForm : Form
    {
        readonly Cap2Py py;
        bool busy, loading;

        // 상단
        readonly TextBox gameBox = new TextBox { ReadOnly = true };
        readonly Label gameState = new Label { AutoSize = false, Dock = DockStyle.Fill, Height = 28, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleLeft };
        // 모드 탭
        readonly ListView modList = new ListView { View = View.Details, CheckBoxes = true, FullRowSelect = true, HideSelection = false, Dock = DockStyle.Fill };
        readonly Label modDesc = new Label { Dock = DockStyle.Fill, AutoEllipsis = true, Padding = new Padding(2, 4, 2, 0) };
        // 동기화 탭
        readonly TextBox syncBox = new TextBox { Dock = DockStyle.Fill };
        readonly TextBox launchBox = new TextBox { ReadOnly = true, Dock = DockStyle.Fill };
        readonly Label saveDirLabel = new Label { AutoSize = false, Dock = DockStyle.Fill, Height = 28, AutoEllipsis = true, TextAlign = ContentAlignment.MiddleLeft };
        // 하단
        readonly RichTextBox logBox = new RichTextBox { ReadOnly = true, Dock = DockStyle.Fill, BorderStyle = BorderStyle.None, WordWrap = false, BackColor = SystemColors.Window };
        readonly StatusStrip status = new StatusStrip();
        readonly ToolStripStatusLabel statusText = new ToolStripStatusLabel { Spring = true, TextAlign = ContentAlignment.MiddleLeft };
        readonly ToolStripStatusLabel pyText = new ToolStripStatusLabel();
        readonly List<Control> actionControls = new List<Control>();
        string modsDir;

        public MainForm()
        {
            Text = "Capitalism 2 모드 매니저";
            Font = new Font("맑은 고딕", 9f);
            AutoScaleMode = AutoScaleMode.Dpi;
            Size = new Size(900, 640);
            MinimumSize = new Size(640, 460);
            StartPosition = FormStartPosition.CenterScreen;
            try { Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath); } catch { }

            var script = Cap2Py.FindScript();
            py = new Cap2Py(script);
            BuildUi();
            Shown += async (s, e) => await StartupAsync();
        }

        // ------------------------------------------------------------------ 화면 구성
        void BuildUi()
        {
            var root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3, Padding = new Padding(10, 8, 10, 4) };
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            root.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            // 게임 폴더 줄
            var top = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 4, AutoSize = true, Margin = new Padding(0, 0, 0, 6) };
            top.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            top.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            top.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            top.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            top.Controls.Add(new Label { Text = "게임 폴더", AutoSize = true, Anchor = AnchorStyles.Left, Padding = new Padding(0, 0, 4, 0) }, 0, 0);
            gameBox.Dock = DockStyle.Fill;
            top.Controls.Add(gameBox, 1, 0);
            top.Controls.Add(Btn("자동 탐지", async () => await RefreshAsync(null, detect: true)), 2, 0);
            top.Controls.Add(Btn("찾기…", BrowseGame), 3, 0);
            top.Controls.Add(gameState, 1, 1);
            top.SetColumnSpan(gameState, 3);
            root.Controls.Add(top, 0, 0);

            // 탭 + 로그 (위아래 분할)
            var split = new SplitContainer { Dock = DockStyle.Fill, Orientation = Orientation.Horizontal, SplitterWidth = 6, FixedPanel = FixedPanel.Panel2 };
            var tabs = new TabControl { Dock = DockStyle.Fill };
            tabs.TabPages.Add(BuildModsTab());
            tabs.TabPages.Add(BuildSyncTab());
            if (Environment.GetCommandLineArgs().Contains("--sync")) tabs.SelectedIndex = 1;   // 바로가기용: 동기화 탭으로 열기
            split.Panel1.Controls.Add(tabs);
            var logGroup = new GroupBox { Text = "기록", Dock = DockStyle.Fill, Padding = new Padding(6, 4, 6, 6) };
            logBox.Font = new Font("Consolas", 9f);
            logGroup.Controls.Add(logBox);
            split.Panel2.Controls.Add(logGroup);
            root.Controls.Add(split, 0, 1);
            Load += (s, e) => { split.SplitterDistance = Math.Max(200, split.Height - 150); split.Panel1MinSize = 180; split.Panel2MinSize = 80; };

            status.Items.Add(statusText);
            status.Items.Add(pyText);
            Controls.Add(root);
            Controls.Add(status);
        }

        TabPage BuildModsTab()
        {
            var page = new TabPage("모드") { Padding = new Padding(6) };
            var t = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 3 };
            t.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            t.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            modList.Columns.Add("이름", 280);
            modList.Columns.Add("id", 130);
            modList.Columns.Add("버전", 70);
            modList.Columns.Add("순서", 50);
            modList.Columns.Add("종류", 260);
            modList.ItemChecked += async (s, e) => { if (!loading) await ToggleAsync(e.Item); };
            modList.SelectedIndexChanged += (s, e) =>
                modDesc.Text = modList.SelectedItems.Count > 0 ? (string)modList.SelectedItems[0].Tag : "";
            t.Controls.Add(modList, 0, 0);
            t.Controls.Add(modDesc, 0, 1);

            var bar = new FlowLayoutPanel { Dock = DockStyle.Fill, AutoSize = true, FlowDirection = FlowDirection.LeftToRight, WrapContents = true, Margin = new Padding(0, 4, 0, 0) };
            var apply = Btn("적용", async () => await RunAsync("모드 적용", "apply"));
            apply.Font = new Font(Font, FontStyle.Bold);
            AcceptButton = (IButtonControl)apply;
            bar.Controls.Add(apply);
            bar.Controls.Add(Btn("원본 복원", async () =>
            {
                if (MessageBox.Show(this, "게임 폴더를 원본으로 되돌릴까요?", Text, MessageBoxButtons.OKCancel, MessageBoxIcon.Question) == DialogResult.OK)
                    await RunAsync("원본 복원", "restore");
            }));
            bar.Controls.Add(Btn("적용 상태 검증", async () => await RunAsync("검증", "verify")));
            bar.Controls.Add(Btn("새로 읽기", async () => await RefreshAsync(gameBox.Text)));
            bar.Controls.Add(Btn("모드 폴더 열기", () => OpenFolder(modsDir)));
            t.Controls.Add(bar, 0, 2);
            page.Controls.Add(t);
            return page;
        }

        TabPage BuildSyncTab()
        {
            var page = new TabPage("세이브 동기화") { Padding = new Padding(10), AutoScroll = true };
            var t = new TableLayoutPanel { Dock = DockStyle.Top, ColumnCount = 3, RowCount = 6, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink };
            t.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            t.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            t.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
            for (int i = 0; i < 6; i++) t.RowStyles.Add(new RowStyle(SizeType.AutoSize));

            var intro = new Label
            {
                AutoSize = true, MaximumSize = new Size(820, 0), Margin = new Padding(0, 0, 0, 10),
                Text = "Capitalism 2는 Steam 클라우드를 지원하지 않습니다. 아래 폴더(네트워크 폴더 또는 smb://주소/공유)를 여러 기기에서 함께 쓰고, " +
                       "Steam 실행 옵션을 넣어 두면 게임 시작 전에 세이브를 받고 종료 후 올립니다."
            };
            t.Controls.Add(intro, 0, 0); t.SetColumnSpan(intro, 3);

            t.Controls.Add(new Label { Text = "동기화 폴더", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 1);
            t.Controls.Add(syncBox, 1, 1);
            var pick = new FlowLayoutPanel { AutoSize = true, WrapContents = false, Margin = Padding.Empty };
            pick.Controls.Add(Btn("찾기…", BrowseSync));
            pick.Controls.Add(Btn("설정 저장", async () =>
            {
                if (syncBox.Text.Trim().Length == 0) { MessageBox.Show(this, "동기화 폴더를 입력하세요.", Text); return; }
                await RunAsync("동기화 폴더 설정", "sync-setup", syncBox.Text.Trim());
            }));
            t.Controls.Add(pick, 2, 1);

            t.Controls.Add(new Label { Text = "이 기기 세이브", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 2);
            t.Controls.Add(saveDirLabel, 1, 2); t.SetColumnSpan(saveDirLabel, 2);

            var now = new FlowLayoutPanel { AutoSize = true, Margin = new Padding(0, 6, 0, 10) };
            now.Controls.Add(Btn("지금 동기화", async () => await RunAsync("동기화", "sync")));
            now.Controls.Add(Btn("받기만", async () => await RunAsync("동기화(받기)", "sync", "--direction", "pull")));
            now.Controls.Add(Btn("올리기만", async () => await RunAsync("동기화(올리기)", "sync", "--direction", "push")));
            now.Controls.Add(Btn("동기화 기록 열기", () => OpenFile(Path.Combine(Path.GetDirectoryName(py.ScriptPath ?? "."), "sync.log"))));
            t.Controls.Add(now, 1, 3); t.SetColumnSpan(now, 2);

            t.Controls.Add(new Label { Text = "Steam 실행 옵션", AutoSize = true, Anchor = AnchorStyles.Left }, 0, 4);
            t.Controls.Add(launchBox, 1, 4);
            t.Controls.Add(Btn("복사", () => { if (launchBox.Text.Length > 0) { Clipboard.SetText(launchBox.Text); SetStatus("실행 옵션을 복사했습니다."); } }), 2, 4);
            var how = new Label
            {
                AutoSize = true, ForeColor = SystemColors.GrayText, MaximumSize = new Size(820, 0),
                Text = "Steam 라이브러리 → Capitalism 2 → 속성 → 일반 → 실행 옵션에 붙여 넣으세요. Steam을 다시 켤 필요는 없습니다."
            };
            t.Controls.Add(how, 1, 5); t.SetColumnSpan(how, 2);
            // 긴 설명은 탭 폭에 맞춰 줄바꿈 (창이 작으면 세로 스크롤)
            page.Resize += (s, e) =>
            {
                int w = Math.Max(200, page.ClientSize.Width - page.Padding.Horizontal - SystemInformation.VerticalScrollBarWidth);
                intro.MaximumSize = new Size(w, 0);
                how.MaximumSize = new Size(Math.Max(150, w - 120), 0);
            };
            page.Controls.Add(t);
            return page;
        }

        Button Btn(string text, Action onClick)
        {
            var b = new Button { Text = text, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink, Padding = new Padding(8, 2, 8, 2), Margin = new Padding(2), UseVisualStyleBackColor = true };
            b.Click += (s, e) => { if (!busy) onClick(); };
            actionControls.Add(b);
            return b;
        }

        // ------------------------------------------------------------------ 동작
        async Task StartupAsync()
        {
            if (py.ScriptPath == null)
            {
                Log("cap2mod.py 를 찾지 못했습니다. 이 프로그램을 모드 매니저 폴더(cap2mod.py 옆)에 두세요.");
                SetBusy(true); return;
            }
            SetStatus("Python 찾는 중…");
            SetBusy(true);
            bool ok = await Task.Run(() => py.DetectPython());
            SetBusy(false);
            pyText.Text = ok ? "Python: " + Path.GetFileName(Path.GetDirectoryName(py.PythonExe)) : "Python 없음";
            pyText.ToolTipText = py.PythonLabel;
            status.ShowItemToolTips = true;
            if (!ok)
            {
                Log("동작하는 Python 3.8 이상을 찾지 못했습니다. https://www.python.org/downloads/ 에서 설치하세요.");
                MessageBox.Show(this, "동작하는 Python 3.8 이상을 찾지 못했습니다.\npython.org에서 설치한 뒤 다시 실행하세요.", Text, MessageBoxButtons.OK, MessageBoxIcon.Warning);
                SetBusy(true); return;
            }
            await RefreshAsync(null);
        }

        async Task RefreshAsync(string game, bool detect = false)
        {
            var args = new List<string>();
            if (!string.IsNullOrEmpty(game) && !detect) { args.Add("--game"); args.Add(game); }
            args.Add("info");
            SetBusy(true);
            try
            {
                var r = await py.RunAsync(args, null);
                var line = r.stdout.Split('\n').Select(x => x.Trim()).LastOrDefault(x => x.StartsWith("{"));
                if (line == null) { Log("정보를 읽지 못했습니다:\n" + r.stdout); return; }
                var info = Json.Parse(line);
                modsDir = Json.Str(info, "mods_dir");
                var g = Json.Obj(info, "game");
                if (detect)
                {
                    var c = Json.Arr(info, "candidates");
                    if (c == null || c.Count == 0) Log("Steam 라이브러리에서 Capitalism 2를 찾지 못했습니다. [찾기…]로 지정하세요.");
                    else if (g == null || !string.Equals(Json.Str(g, "dir"), (string)c[0], StringComparison.OrdinalIgnoreCase))
                    { await RefreshAsync((string)c[0]); return; }
                }
                if (g != null)
                {
                    gameBox.Text = Json.Str(g, "dir");
                    var ap = Json.Obj(g, "applied");
                    var mods = Json.Arr(ap, "mods");
                    gameState.Text = Json.Str(g, "build") + "  ·  " +
                        (ap == null ? "원본 상태(적용된 모드 없음)"
                                    : "적용됨 " + Json.Str(ap, "at") + " (" + string.Join(", ", mods.Select(m => Json.Str(m, "id") + " " + Json.Str(m, "version"))) + ")");
                    saveDirLabel.Text = Json.Str(g, "save_dir") ?? "(아직 없음 — 게임을 한 번 실행하면 생깁니다)";
                }
                else
                {
                    gameBox.Text = "";
                    gameState.Text = Json.Str(info, "game_error") ?? "게임 폴더를 지정하세요.";
                }
                var cfg = Json.Obj(info, "config");
                syncBox.Text = Json.Str(cfg, "sync_dir") ?? syncBox.Text;
                launchBox.Text = Json.Str(info, "launch_option") ?? "";

                loading = true;
                modList.BeginUpdate();
                modList.Items.Clear();
                foreach (var m in Json.Arr(info, "mods") ?? new List<object>())
                {
                    var it = new ListViewItem(Json.Str(m, "name")) { Checked = Json.Bool(m, "enabled"), Name = Json.Str(m, "id") };
                    it.SubItems.Add(Json.Str(m, "id"));
                    it.SubItems.Add(Json.Str(m, "version"));
                    it.SubItems.Add(Json.Str(m, "priority"));
                    it.SubItems.Add(Json.Str(m, "kinds"));
                    it.Tag = Json.Str(m, "description");
                    if (Json.Str(m, "id").StartsWith("_")) it.ForeColor = SystemColors.GrayText;
                    modList.Items.Add(it);
                }
                modList.EndUpdate();
                loading = false;
                if (statusText.Text.EndsWith("…")) SetStatus("준비됨");
            }
            catch (Exception ex) { Log("오류: " + ex.Message); }
            finally { loading = false; SetBusy(false); }
        }

        async Task ToggleAsync(ListViewItem it)
        {
            await RunAsync(null, it.Checked ? "enable" : "disable", it.Name);
        }

        async Task RunAsync(string title, params string[] args)
        {
            if (busy) return;
            var full = new List<string>();
            if (gameBox.Text.Length > 0 && args[0] != "enable" && args[0] != "disable") { full.Add("--game"); full.Add(gameBox.Text); }
            full.AddRange(args);
            SetBusy(true);
            if (title != null) { Log(""); Log("▶ " + title, bold: true); SetStatus(title + " 중…"); }
            int code = -1;
            try
            {
                var r = await py.RunAsync(full, line => BeginInvoke((Action)(() => Log(line))));
                code = r.code;
            }
            catch (Exception ex) { Log("오류: " + ex.Message); }
            finally { SetBusy(false); }
            if (title != null)
            {
                SetStatus(code == 0 ? title + " 완료" : title + " 실패 (기록 확인)");
                if (code != 0) Log("✖ " + title + " 실패 (종료 코드 " + code + ")", bold: true);
            }
            if (args[0] != "sync") await RefreshAsync(gameBox.Text);
        }

        void BrowseGame()
        {
            using (var d = new OpenFileDialog { Title = "Cap2.exe 선택", Filter = "Capitalism 2 (Cap2.exe)|Cap2.exe", CheckFileExists = true })
            {
                if (gameBox.Text.Length > 0 && Directory.Exists(gameBox.Text)) d.InitialDirectory = gameBox.Text;
                if (d.ShowDialog(this) == DialogResult.OK) _ = RefreshAsync(Path.GetDirectoryName(d.FileName));
            }
        }

        void BrowseSync()
        {
            using (var d = new FolderBrowserDialog { Description = "여러 기기가 함께 쓸 세이브 동기화 폴더", ShowNewFolderButton = true })
            {
                if (Directory.Exists(syncBox.Text)) d.SelectedPath = syncBox.Text;
                if (d.ShowDialog(this) == DialogResult.OK) syncBox.Text = d.SelectedPath;
            }
        }

        void OpenFolder(string p)
        {
            if (!string.IsNullOrEmpty(p) && Directory.Exists(p)) Process.Start("explorer.exe", "\"" + p + "\"");
        }

        void OpenFile(string p)
        {
            if (File.Exists(p)) Process.Start(new ProcessStartInfo(p) { UseShellExecute = true });
            else SetStatus("아직 기록이 없습니다.");
        }

        void SetBusy(bool b)
        {
            busy = b;
            foreach (var c in actionControls) c.Enabled = !b;
            modList.Enabled = !b;
            UseWaitCursor = b;
        }

        void SetStatus(string s) => statusText.Text = s;

        void Log(string s, bool bold = false)
        {
            if (logBox.IsDisposed) return;
            logBox.SelectionStart = logBox.TextLength;
            logBox.SelectionFont = bold ? new Font(logBox.Font, FontStyle.Bold) : logBox.Font;
            logBox.SelectionColor = s.StartsWith("경고") ? Color.DarkOrange : s.StartsWith("오류") || s.StartsWith("✖") ? Color.Firebrick : logBox.ForeColor;
            logBox.AppendText(s + "\n");
            logBox.ScrollToCaret();
        }
    }
}
