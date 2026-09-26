(() => {
  function byId(id) {
    return document.getElementById(id);
  }

  function bytes(value) {
    if (!Number.isFinite(value)) return "";

    const units = ["B", "KB", "MB", "GB", "TB"];
    let size = value;
    let unit = 0;

    while (size >= 1024 && unit < units.length - 1) {
      size /= 1024;
      unit += 1;
    }

    const rounded =
      size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(1);

    return rounded + " " + units[unit];
  }

  function showStatus(message) {
    const node = byId("webvm-status");
    if (node) node.textContent = message;
  }

  function openKeyboard() {
    const button =
      document.querySelector("#noVNC_keyboard_button") ||
      document.querySelector("#showKeyboard");

    if (button) {
      button.click();

      setTimeout(() => {
        const input =
          document.querySelector("#noVNC_keyboardinput") ||
          document.querySelector("#keyboardinput");

        if (input) input.focus({ preventScroll: true });
      }, 80);

      showStatus("Teclado virtual aberto");
      return;
    }

    const input =
      document.querySelector("#noVNC_keyboardinput") ||
      document.querySelector("#keyboardinput");

    if (input) {
      input.focus({ preventScroll: true });
      showStatus("Campo de teclado focado");
      return;
    }

    showStatus(
      "O visualizador ainda está a iniciar. Toca em Teclado novamente."
    );
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function refreshFiles() {
    try {
      const response = await fetch("/api/files", { cache: "no-store" });
      const data = await response.json();
      const list = byId("webvm-upload-list");

      if (!list) return;

      if (!Array.isArray(data.files) || data.files.length === 0) {
        list.innerHTML = "<div>Ainda não há ficheiros enviados.</div>";
        return;
      }

      list.innerHTML = data.files
        .slice(0, 12)
        .map(function (file) {
          return (
            '<div class="webvm-file"><span title="' +
            escapeHtml(file.name) +
            '">' +
            escapeHtml(file.name) +
            "</span><span>" +
            bytes(Number(file.size)) +
            "</span></div>"
          );
        })
        .join("");
    } catch {
      // Convenience feature only.
    }
  }

  async function uploadFiles(files) {
    if (!files || files.length === 0) return;

    const form = new FormData();

    for (const file of files) {
      form.append("files", file, file.name);
    }

    showStatus("A enviar " + files.length + " ficheiro(s)...");

    try {
      const response = await fetch("/api/upload", {
        method: "POST",
        body: form,
      });

      const data = await response.json().catch(function () {
        return {};
      });

      if (!response.ok) {
        throw new Error(data.error || "Falha no upload.");
      }

      showStatus(
        (data.files?.length || files.length) +
          " ficheiro(s) enviado(s) para Shared"
      );

      await refreshFiles();
      byId("webvm-upload-list")?.classList.add("open");
    } catch (error) {
      showStatus(error?.message || "Falha no upload.");
    }
  }

  function buildToolbar() {
    if (byId("webvm-portal-toolbar")) return;

    const toolbar = document.createElement("div");
    toolbar.id = "webvm-portal-toolbar";
    toolbar.innerHTML =
      '<label for="webvm-upload" title="Enviar ficheiros para a pasta Shared do Windows">📤 Enviar ficheiros</label>' +
      '<input id="webvm-upload" type="file" multiple>' +
      '<button id="webvm-keyboard" type="button" title="Abrir o teclado no iPad">⌨️ Teclado</button>' +
      '<button id="webvm-files" type="button" title="Mostrar os últimos ficheiros enviados">📁 Ficheiros</button>' +
      '<span id="webvm-status" role="status" aria-live="polite">Windows online</span>';

    const list = document.createElement("div");
    list.id = "webvm-upload-list";
    list.setAttribute("aria-live", "polite");

    document.body.appendChild(toolbar);
    document.body.appendChild(list);

    byId("webvm-upload").addEventListener(
      "change",
      async function (event) {
        await uploadFiles(event.target.files);
        event.target.value = "";
      }
    );

    byId("webvm-keyboard").addEventListener("click", openKeyboard);

    byId("webvm-files").addEventListener("click", async function () {
      const panel = byId("webvm-upload-list");
      panel.classList.toggle("open");

      if (panel.classList.contains("open")) {
        await refreshFiles();
      }
    });

    refreshFiles();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", buildToolbar, { once: true });
  } else {
    buildToolbar();
  }
})();
