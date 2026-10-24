using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Windows;
using Microsoft.Win32;

namespace RawArchiver;

public partial class MainWindow : Window
{
    private readonly IpcClient _client = new();
    private bool _previewed = false;
    private string _taskId = "";
    private string _varDir = "";

    public MainWindow()
    {
        InitializeComponent();
        _varDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), "RawArchiver");
        Directory.CreateDirectory(_varDir);
        LoadSettings();

        _client.OnEvent += OnIpcEvent;

        Loaded += async (_, _) => await StartupAsync();
        Closed += (_, _) => { SaveSettings(); _client.Stop(); };
    }

    private async System.Threading.Tasks.Task StartupAsync()
    {
        var cli = IpcClient.LocateCli();
        if (cli == null)
        {
            StatusText.Text = "未找到核心引擎（RawArchiver-cli.exe）";
            return;
        }
        _client.Launch(cli, _varDir);
        try
        {
            var resp = await _client.Request("doctor");
            var r = (Dictionary<string, object>)resp["result"];
            StatusText.Text = $"ExifTool: {Convert.Str(r["exiftool"])} | exifread: {Convert.Bool(r["exifread"])} | Pillow: {Convert.Bool(r["pillow"])}";
        }
        catch (Exception ex)
        {
            StatusText.Text = "自检失败: " + ex.Message;
        }
    }

    private Dictionary<string, object> BuildOpts() => new()
    {
        ["brandFolder"] = BrandCheck.IsChecked == true,
        ["handleJpg"] = JpgCheck.IsChecked == true,
        ["handleVideo"] = VideoCheck.IsChecked == true,
        ["staging"] = StagingCheck.IsChecked == true,
        ["mode"] = ((ComboBoxItem)ModeCombo.SelectedItem)?.Tag?.ToString() ?? "copy",
    };

    private async void PreviewButton_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrWhiteSpace(SourceBox.Text) || string.IsNullOrWhiteSpace(OutputBox.Text))
        {
            MessageBox.Show("请先填写源与输出目录", "提示", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }
        PreviewButton.IsEnabled = false;
        StatusText.Text = "正在扫描源…";
        try
        {
            var resp = await _client.Request("preview", new Dictionary<string, object>
            {
                ["source"] = SourceBox.Text,
                ["output"] = OutputBox.Text,
                ["opts"] = BuildOpts(),
            });
            var result = (Dictionary<string, object>)resp["result"];
            var samples = Convert.DictList(result["sample"]).Select(s => new PreviewSample
            {
                Src = Convert.Str(s["src"]),
                Date = Convert.Str(s["date"]),
                DateFrom = Convert.Str(s["date_from"]),
                Dst = Convert.Str(s["dst_rel"]),
                Bad = Convert.Bool(s["bad"]),
            }).ToList();

            long total = Convert.Long(result["total"]);
            long size = Convert.Long(result["size"]);
            var range = ExtractRange(result);
            bool exiftool = Convert.Bool(result["exiftool"]);

            SummaryText.Text = $"{total} 个文件 / {size / 1073741824.0:F2} GB ｜ 日期 {range.Item1} ~ {range.Item2} ｜ ExifTool: {(exiftool ? "可用" : "未找到")}";
            WarningText.Text = BuildWarnings(result);

            PreviewGrid.ItemsSource = samples;
            PreviewGrid.Visibility = Visibility.Visible;
            _previewed = true;
            StartButton.IsEnabled = true;
            StatusText.Text = "预览完成";
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "预览失败", MessageBoxButton.OK, MessageBoxImage.Error);
            StatusText.Text = "预览失败";
        }
        finally
        {
            PreviewButton.IsEnabled = true;
        }
    }

    private (string, string) ExtractRange(Dictionary<string, object> result)
    {
        var list = result.TryGetValue("date_range", out var v) ? v as List<object?> : null;
        if (list != null && list.Count >= 2)
            return (list[0]?.ToString() ?? "", list[1]?.ToString() ?? "");
        return ("", "");
    }

    private string BuildWarnings(Dictionary<string, object> result)
    {
        var w = "";
        long bad = Convert.Long(result["bad_count"]);
        long skip = Convert.Long(result["raw_skip_hint"]);
        long conflicts = Convert.Long(result["conflicts"]);
        bool removable = Convert.Bool(result["removable"]);
        if (bad > 0) w += $"注意：{bad} 个文件只能靠文件修改时间推断日期，请核对后再执行。\n";
        if (skip > 0) w += $"提示：{skip} 个照片读不到拍摄日期，执行时将被跳过。\n";
        if (conflicts > 0) w += $"提示：{conflicts} 个目标已存在同名文件，将自动追加 _1/_2。\n";
        if (removable && GetMode() == "move")
            w += "源为可移动设备，移动模式下归档完成后将清空源设备，此操作不可回滚。";
        return w;
    }

    private async void StartButton_Click(object sender, RoutedEventArgs e)
    {
        if (!_previewed) return;
        if (GetMode() == "move")
        {
            var r = MessageBox.Show("确认归档后清空源设备上的文件？此操作不可回滚。", "确认",
                MessageBoxButton.YesNo, MessageBoxImage.Warning);
            if (r != MessageBoxResult.Yes) return;
        }
        StartButton.IsEnabled = false;
        CancelButton.IsEnabled = true;
        LogBox.Clear();
        ProgressPanel.Visibility = Visibility.Visible;
        PreviewGrid.Visibility = Visibility.Collapsed;
        try
        {
            var resp = await _client.Request("start", new Dictionary<string, object>
            {
                ["source"] = SourceBox.Text,
                ["output"] = OutputBox.Text,
                ["opts"] = BuildOpts(),
            });
            var result = (Dictionary<string, object>)resp["result"];
            _taskId = Convert.Str(result["taskId"]);
            StatusText.Text = "正在归档…";
        }
        catch (Exception ex)
        {
            MessageBox.Show(ex.Message, "启动失败", MessageBoxButton.OK, MessageBoxImage.Error);
            StartButton.IsEnabled = true;
            CancelButton.IsEnabled = false;
        }
    }

    private void CancelButton_Click(object sender, RoutedEventArgs e)
    {
        if (string.IsNullOrEmpty(_taskId)) return;
        _ = _client.Request("cancel", new Dictionary<string, object> { ["taskId"] = _taskId });
        StatusText.Text = "正在取消…";
    }

    private void OnIpcEvent(string evt, Dictionary<string, object> obj)
    {
        Dispatcher.Invoke(() =>
        {
            if (evt == "progress")
            {
                long current = Convert.Long(obj["current"]);
                long total = Convert.Long(obj["total"]);
                long success = Convert.Long(obj["success"]);
                long failed = Convert.Long(obj["failed"]);
                long skipped = Convert.Long(obj["skipped"]);
                TaskProgress.Maximum = Math.Max(total, 1);
                TaskProgress.Value = Math.Min(current, TaskProgress.Maximum);
                ProgressText.Text = $"{Convert.Str(obj["status"])}  {current}/{total} ｜ 成功 {success} 失败 {failed} 跳过 {skipped}";
                AppendLogs(Convert.DictList(obj["logs"]));
            }
            else if (evt == "done")
            {
                string status = Convert.Str(obj["status"]);
                long success = Convert.Long(obj["success"]);
                long failed = Convert.Long(obj["failed"]);
                long skipped = Convert.Long(obj["skipped"]);
                StartButton.IsEnabled = true;
                CancelButton.IsEnabled = false;
                StatusText.Text = status;
                if (status == "error")
                    MessageBox.Show(Convert.Str(obj["error"]), "归档出错", MessageBoxButton.OK, MessageBoxImage.Error);
                else
                    LogBox.AppendText($"\n完成：成功 {success} / 失败 {failed} / 跳过 {skipped}\n");
            }
        });
    }

    private void AppendLogs(List<Dictionary<string, object>> logs)
    {
        foreach (var it in logs)
        {
            string t = Convert.Str(it["t"]);
            if (it.TryGetValue("msg", out var msg))
                LogBox.AppendText($"[{t}] {msg}\n");
            else if (it.TryGetValue("src", out var src) && it.TryGetValue("dst", out var dst))
                LogBox.AppendText($"[{t}] {src} -> {dst}\n");
        }
        LogBox.ScrollToEnd();
    }

    private string GetMode() => ((ComboBoxItem)ModeCombo.SelectedItem)?.Tag?.ToString() ?? "copy";

    private void SourceButton_Click(object sender, RoutedEventArgs e) => PickFolder(SourceBox);
    private void OutputButton_Click(object sender, RoutedEventArgs e) => PickFolder(OutputBox);

    private void PickFolder(System.Windows.Controls.TextBox box)
    {
        var dlg = new OpenFolderDialog { Title = "选择目录" };
        if (dlg.ShowDialog() == true)
        {
            box.Text = dlg.FolderName;
        }
    }

    private void OpenOutButton_Click(object sender, RoutedEventArgs e)
    {
        if (!string.IsNullOrWhiteSpace(OutputBox.Text) && Directory.Exists(OutputBox.Text))
            Process.Start(new ProcessStartInfo("explorer.exe", $"\"{OutputBox.Text}\"") { UseShellExecute = true });
    }

    private void AboutButton_Click(object sender, RoutedEventArgs e)
    {
        MessageBox.Show($"RAW 归档 v1.1.0\n数据目录：{_varDir}", "关于", MessageBoxButton.OK, MessageBoxImage.Information);
    }

    private void SourceBox_TextChanged(object sender, System.Windows.Controls.TextChangedEventArgs e) => _previewed = false;
    private void OutputBox_TextChanged(object sender, System.Windows.Controls.TextChangedEventArgs e) => _previewed = false;
    private void OptionChanged(object sender, RoutedEventArgs e) => _previewed = false;

    // ---- 设置持久化 ----
    private string SettingsPath => Path.Combine(_varDir, "settings.json");

    private void LoadSettings()
    {
        try
        {
            if (!File.Exists(SettingsPath)) return;
            var json = JsonDocument.Parse(File.ReadAllText(SettingsPath));
            var root = json.RootElement;
            if (root.TryGetProperty("source", out var s)) SourceBox.Text = s.GetString();
            if (root.TryGetProperty("output", out var o)) OutputBox.Text = o.GetString();
            if (root.TryGetProperty("brandFolder", out var b)) BrandCheck.IsChecked = b.GetBoolean();
            if (root.TryGetProperty("handleJpg", out var j)) JpgCheck.IsChecked = j.GetBoolean();
            if (root.TryGetProperty("handleVideo", out var v)) VideoCheck.IsChecked = v.GetBoolean();
            if (root.TryGetProperty("staging", out var st)) StagingCheck.IsChecked = st.GetBoolean();
            if (root.TryGetProperty("mode", out var m))
            {
                var mv = m.GetString();
                foreach (var item in ModeCombo.Items)
                    if (item is ComboBoxItem cbi && cbi.Tag?.ToString() == mv) ModeCombo.SelectedItem = cbi;
            }
        }
        catch { }
    }

    private void SaveSettings()
    {
        try
        {
            var obj = new Dictionary<string, object>
            {
                ["source"] = SourceBox.Text,
                ["output"] = OutputBox.Text,
                ["brandFolder"] = BrandCheck.IsChecked == true,
                ["handleJpg"] = JpgCheck.IsChecked == true,
                ["handleVideo"] = VideoCheck.IsChecked == true,
                ["staging"] = StagingCheck.IsChecked == true,
                ["mode"] = GetMode(),
            };
            File.WriteAllText(SettingsPath, JsonSerializer.Serialize(obj));
        }
        catch { }
    }
}

public class PreviewSample
{
    public string Src { get; set; } = "";
    public string Date { get; set; } = "";
    public string DateFrom { get; set; } = "";
    public string Dst { get; set; } = "";
    public bool Bad { get; set; }
}
