(function () {
  var COLORS = [
    ["#8c1d40", "酒紅 / Maroon"],
    ["#c0392b", "紅 / Red"],
    ["#d97706", "橘 / Orange"],
    ["#1f7a4d", "綠 / Green"],
    ["#1d4ed8", "藍 / Blue"],
    ["#111111", "黑 / Black"]
  ];

  function enhance(textarea) {
    var wrapper = document.createElement("div");
    wrapper.className = "rich-note-editor";

    var toolbar = document.createElement("div");
    toolbar.className = "rich-note-toolbar";
    toolbar.setAttribute("role", "toolbar");

    var editor = document.createElement("div");
    editor.className = "rich-note-surface";
    editor.contentEditable = "true";
    editor.setAttribute("role", "textbox");
    editor.setAttribute("aria-multiline", "true");

    function addButton(label, title, command, value, className) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "rich-note-button" + (className ? " " + className : "");
      button.title = title;
      button.setAttribute("aria-label", title);
      if (value && command === "foreColor") {
        button.style.background = value;
      } else {
        button.innerHTML = label;
      }
      // mousedown 阻止預設行為,避免點工具列時編輯區失去選取範圍。
      button.addEventListener("mousedown", function (event) { event.preventDefault(); });
      button.addEventListener("click", function () {
        editor.focus();
        document.execCommand("styleWithCSS", false, true);
        document.execCommand(command, false, value || null);
        sync();
      });
      toolbar.appendChild(button);
    }

    addButton("<b>B</b>", "粗體 / Bold", "bold");
    addButton("<i>I</i>", "斜體 / Italic", "italic");
    addButton("<u>U</u>", "底線 / Underline", "underline");
    COLORS.forEach(function (color) {
      addButton("", "文字顏色 / Text color: " + color[1], "foreColor", color[0], "rich-note-swatch");
    });
    addButton("清除", "清除格式 / Clear formatting", "removeFormat");

    function sync() {
      var text = (editor.textContent || "").replace(/ /g, " ").trim();
      textarea.value = text ? editor.innerHTML : "";
    }

    editor.addEventListener("input", sync);
    // 貼上一律轉成純文字,避免帶入外部網頁的字型/背景等雜訊(伺服器端仍會再清理一次)。
    editor.addEventListener("paste", function (event) {
      var clipboard = event.clipboardData || window.clipboardData;
      if (!clipboard) { return; }
      event.preventDefault();
      document.execCommand("insertText", false, clipboard.getData("text/plain"));
    });

    textarea.hidden = true;
    textarea.parentNode.insertBefore(wrapper, textarea);
    wrapper.appendChild(toolbar);
    wrapper.appendChild(editor);
    wrapper.appendChild(textarea);

    if (textarea.form) {
      textarea.form.addEventListener("submit", sync);
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("textarea[data-rich-note]").forEach(enhance);
  });
})();
