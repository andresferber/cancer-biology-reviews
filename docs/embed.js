/* Cancer Biology Reviews: embed for andresferber.org (Weebly "Embed Code" element).
   <div id="cancer-biology-reviews"></div>
   <script src="https://andresferber.github.io/cancer-biology-reviews/embed.js"></script>
   Puts the page in a frame (so the site's styles cannot interfere) and keeps the frame as tall as its content. */
(function () {
  var HOST = "https://andresferber.github.io";
  var SRC = HOST + "/cancer-biology-reviews/";
  var box = document.getElementById("cancer-biology-reviews");
  if (!box) return;
  var f = document.createElement("iframe");
  f.src = SRC;
  f.title = "Cancer Biology Reviews";
  f.setAttribute("loading", "lazy");
  f.style.cssText = "width:100%;border:0;min-height:700px;display:block";
  box.appendChild(f);
  window.addEventListener("message", function (e) {
    if (e.origin !== HOST || e.source !== f.contentWindow) return;
    var h = e.data && e.data.cbrHeight;
    if (typeof h === "number" && h > 0 && h < 100000) f.style.height = h + 8 + "px";
  });
})();
