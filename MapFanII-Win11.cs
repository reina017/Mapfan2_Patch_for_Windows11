using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Windows.Forms;

internal static class MapFanIIWin11 {
    [STAThread]
    static void Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        try {
            Directory.SetCurrentDirectory(root);
            string main = Path.Combine(root, "MapFan2.exe");
            string server = Path.Combine(root, "SDBOLE32.exe");
            if (!File.Exists(main) || !File.Exists(server))
                throw new FileNotFoundException("MapFan2.exe / SDBOLE32.exe was not found in the installation folder.");
            using (var mutex = new Mutex(false, "Local\\MapFanIIWin11Launcher")) {
                if (!mutex.WaitOne(0)) return;
                try {
                    var start = new ProcessStartInfo(server, "-Embedding");
                    start.WorkingDirectory = root;
                    start.UseShellExecute = false;
                    start.CreateNoWindow = true;
                    start.WindowStyle = ProcessWindowStyle.Hidden;
                    using (Process helper = Process.Start(start)) {
                        try { helper.WaitForInputIdle(5000); } catch (InvalidOperationException) {}
                        if (helper.HasExited) throw new Exception("The MapFan OLE component could not start.");
                        var app = new ProcessStartInfo(main);
                        app.WorkingDirectory = root;
                        app.UseShellExecute = false;
                        using (Process process = Process.Start(app)) process.WaitForExit();
                    }
                } finally { mutex.ReleaseMutex(); }
            }
        } catch (Exception error) {
            MessageBox.Show(error.Message, "MapFan II Windows 11 launcher", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
