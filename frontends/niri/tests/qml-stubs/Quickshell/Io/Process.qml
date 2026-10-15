import QtQuick

// Stub of Quickshell.Io.Process that NEVER SPAWNS ANYTHING.
//
// This matters beyond convenience. The installer's third Process runs the real
// backend, which runs fisherman, which partitions a disk. A stub that actually
// executed `command` would repartition whatever machine rendered the docs. So
// this one serves canned output per backend subcommand and exits 0.
QtObject {
    id: proc

    property var command: []
    property bool running: false
    property bool stdinEnabled: false
    property var stdout: null
    property var stderr: null
    signal exited(int code, int status)
    signal started()

    // Mirror the real Process: write() is fed on started(). The real
    // backend reads the recipe from stdin so the LUKS passphrase never
    // lands in /proc/PID/cmdline. It is kept in `written` so the end-to-end
    // driver (tests/e2e/run.py) can hand exactly what the QML wrote to the
    // real backend; nothing here executes it.
    property string written: ""
    function write(data) { written = data }

    // Canned backend output. Shapes match installer/main.go: `detect` returns
    // live facts, TPM and requirements (the harnesses set encryptionChoices
    // from installer/encryption-choices.json); `validate` answers "valid";
    // `discover-disks` returns the disks
    // fisherman's probe offers (installer/probe.go, ProbeDisk). The capture
    // harness replaces the disks with shared/probe/fixtures/laptop.expected.json.
    readonly property var fixtures: ({
        "detect": JSON.stringify({
            isLive: false,
            liveImage: "",
            offlineImages: [],
            hasTpm: true,
            unmet: [],
            // What a branding.json on the docs product would yield; the
            // walkthrough is captured with this, not with the runner's
            // os-release.
            branding: {
                name: "TunaOS", id: "tunaos", defaultHostname: "tunaos",
                defaultImage: "ghcr.io/tuna-os/albacore:gnome"
            }
        }),
        "validate": JSON.stringify({ protocol_version: 1, valid: true, errors: [] }),
        "discover-disks": JSON.stringify([
            { path: "/dev/nvme0n1", title: "WD_BLACK SN850X 1000GB", model: "WD_BLACK SN850X 1000GB",
              size_label: "953.9 GiB", transport_label: "NVMe", removable: false }
        ])
    })

    onRunningChanged: {
        if (!running) return
        started()
        const sub = command.length > 1 ? command[1] : ""
        const payload = fixtures[sub] !== undefined ? fixtures[sub] : ""
        if (stdout && stdout.feed) stdout.feed(payload)
        Qt.callLater(function () {
            proc.running = false
            proc.exited(0, 0)
        })
    }
}
