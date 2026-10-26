"use strict";
(() => {
  const data = JSON.parse(document.getElementById("course-data").textContent);
  // Browser QA reads the JSON actually loaded by this page and these markers.
  document.documentElement.dataset.readerPayloadSha256 = data.reader_payload_sha256 || "";
  document.documentElement.dataset.sourceManifestSha256 = data.source_manifest_sha256 || "";
  document.documentElement.dataset.appJsSha256 = data.asset_versions?.app_js || "";
  document.documentElement.dataset.appCssSha256 = data.asset_versions?.app_css || "";
  const lessons = data.lessons || [];
  const byId = new Map(lessons.map((lesson, index) => [lesson.id, {lesson, index}]));
  const $ = id => document.getElementById(id);
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const safeHref = value => {
    if (!value) return "";
    try { const url = new URL(value, location.href); return ["http:", "https:", "file:"].includes(url.protocol) ? escape(value) : ""; } catch { return ""; }
  };
  const highlight = (text, query) => {
    if (!query) return escape(text);
    const lower = String(text).toLocaleLowerCase(), needle = query.toLocaleLowerCase();
    let start = 0, result = "", at;
    while ((at = lower.indexOf(needle, start)) !== -1) { result += escape(String(text).slice(start, at)) + "<mark>" + escape(String(text).slice(at, at + query.length)) + "</mark>"; start = at + query.length; }
    return result + escape(String(text).slice(start));
  };
  let active = null, fontSize = 18;
  try { fontSize = Math.max(15, Math.min(24, Number(localStorage.getItem("course-font-size")) || 18)); } catch {}
  document.documentElement.style.setProperty("--reader-size", fontSize + "px");
  $("course-title").textContent = data.title;
  $("course-summary").textContent = `正文 ${data.summary.imported} / ${lessons.length} 讲 · 音频 ${data.summary.audio} 段 · 视频 ${data.summary.video || 0} 段`;
  if (data.cover_path && safeHref(data.cover_path)) { $("course-cover").src = data.cover_path; $("course-cover").hidden = false; }
  if (data.source_url && safeHref(data.source_url)) $("course-source").href = data.source_url; else $("course-source").hidden = true;

  function renderList() {
    const query = $("search").value.trim();
    const terms = query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
    let section = null, count = 0;
    const list = lessons.map((lesson, index) => {
      const haystack = `${lesson.title} ${lesson.section || ""} ${lesson.text || ""}`.toLocaleLowerCase();
      if (!terms.every(term => haystack.includes(term))) return "";
      count++;
      let group = "";
      if (lesson.section && lesson.section !== section) { group = `<div class="lesson-group">${escape(lesson.section)}</div>`; section = lesson.section; }
      let excerpt = "";
      if (query && !lesson.title.toLocaleLowerCase().includes(query.toLocaleLowerCase())) {
        const at = (lesson.text || "").toLocaleLowerCase().indexOf(terms[0]);
        if (at >= 0) excerpt = `<span class="lesson-excerpt">${at > 24 ? "…" : ""}${highlight(lesson.text.slice(Math.max(0, at - 24), at + 70), terms[0])}…</span>`;
      }
      return group + `<a href="#lesson=${encodeURIComponent(lesson.id)}" class="lesson-link${lesson.imported ? " imported" : ""}" ${active === lesson.id ? 'aria-current="page"' : ""} data-lesson-id="${escape(lesson.id)}"><span class="number">${String(index + 1).padStart(2, "0")}</span><span>${highlight(lesson.title, query)}</span><span class="lesson-state" title="${lesson.imported ? "正文已保存" : "正文未导入"}"></span>${excerpt}</a>`;
    }).join("");
    $("lesson-list").innerHTML = list || `<p class="no-results">${lessons.length ? "没有匹配的课程，试试其他关键词。" : "尚未导入课程目录。"}</p>`;
    $("search-results").textContent = query ? `找到 ${count} / ${lessons.length} 讲` : "按课程原始顺序排列";
  }

  function attachSubtitles(lesson) {
    const subtitles = (lesson.subtitles || []).filter(track => track.format === "vtt" && safeHref(track.path));
    const videos = Array.from($("reading-area").querySelectorAll("video"));
    videos.forEach((video, index) => {
      const path = video.getAttribute("src") || video.querySelector("source[src]")?.getAttribute("src");
      const media = (lesson.video || []).find(track => track.path === path);
      const videoIndex = Number(media?.video_index ?? video.dataset.videoIndex ?? index);
      const tracks = subtitles.filter(track => Number(track.video_index || 0) === videoIndex);
      const preferred = tracks.find(track => track.preferred) || tracks[0];
      tracks.forEach((subtitle, n) => {
        if (Array.from(video.querySelectorAll("track")).some(track => track.getAttribute("src") === subtitle.path)) return;
        const track = document.createElement("track");
        track.kind = "subtitles"; track.srclang = "zh"; track.label = `${subtitle.label || "中文字幕"}${tracks.length > 1 ? ` ${n + 1}` : ""}`;
        track.src = subtitle.path; track.default = subtitle === preferred;
        video.appendChild(track);
      });
    });
  }

  function renderLesson(id) {
    const entry = byId.get(id);
    if (!entry) {
      active = null;
      $("reading-area").innerHTML = '<section class="empty-state"><div class="empty-number" aria-hidden="true">读</div><h2>课程资料尚未导入</h2><p>阅读界面已就绪。课程正文、图片、音频和视频导入本地后，会在这里按原始目录呈现。</p><p class="import-guide">导入进度与缺失素材以本地清单为准。</p></section>';
      $("lesson-position").textContent = "LOCAL LIBRARY"; renderList(); return;
    }
    const {lesson, index} = entry;
    const changed = active !== lesson.id;
    active = lesson.id;
    document.querySelectorAll("audio,video").forEach(media => media.pause());
    const sourceDocument = new DOMParser().parseFromString(lesson.html || "", "text/html");
    const inlineAudioLabels = new Map(Array.from(sourceDocument.querySelectorAll("audio[src],audio source[src]"), media => [media.getAttribute("src"), media.closest(".source-audio")?.querySelector("p")?.textContent]));
    const inlineVideoLabels = new Map(Array.from(sourceDocument.querySelectorAll("video[src],video source[src]"), media => [media.getAttribute("src"), media.closest("figure,.source-video")?.querySelector("figcaption,p")?.textContent]));
    const source = safeHref(lesson.source_url);
    const files = [lesson.markdown_path ? `<a href="${safeHref(lesson.markdown_path)}" download>下载 Markdown ↓</a>` : "", lesson.html_path ? `<a href="${safeHref(lesson.html_path)}" download>保存的正文 HTML ↓</a>` : "", ...(lesson.audio || []).filter(track => inlineAudioLabels.has(track.path)).map(track => `<a href="${safeHref(track.path)}" download>下载音频 · ${escape(inlineAudioLabels.get(track.path) || track.label || "课程音频")} ↓</a>`), ...(lesson.video || []).filter(track => inlineVideoLabels.has(track.path)).map(track => `<a href="${safeHref(track.path)}" download>下载视频 · ${escape(inlineVideoLabels.get(track.path) || track.label || "课程视频")} ↓</a>`), ...(lesson.video_audio_components || []).flatMap(track => [`<a href="${safeHref(track.path)}" download>下载${escape(track.label || "视频音轨")} ↓</a>`, track.encrypted_source ? `<a href="${safeHref(track.encrypted_source.path)}" download>源音频备份（不可直接播放） ↓</a>` : ""]), ...(lesson.subtitles || []).map(track => `<a href="${safeHref(track.path)}" download>下载 ${escape(track.label || (track.format || "字幕").toUpperCase())} ↓</a>`), source ? `<a href="${source}" target="_blank" rel="noopener noreferrer">查看原文 ↗</a>` : ""].filter(Boolean).join("");
    const audio = (lesson.audio || []).filter(track => !inlineAudioLabels.has(track.path)).map((track, n) => `<div class="audio-track"><label for="audio-${n}">${escape(track.label || "课程音频")}</label><audio id="audio-${n}" controls preload="none" src="${safeHref(track.path)}">此浏览器无法播放音频，请使用下载链接。</audio><a class="audio-download" href="${safeHref(track.path)}" download>下载音频 ↓</a></div>`).join("");
    const video = (lesson.video || []).filter(track => !inlineVideoLabels.has(track.path)).map((track, n) => `<div class="video-track"><label for="video-${n}">${escape(track.label || "课程视频")}</label><video id="video-${n}" data-video-index="${Number(track.video_index || 0)}" controls playsinline preload="none" src="${safeHref(track.path)}"${track.poster ? ` poster="${safeHref(track.poster)}"` : ""}>此浏览器无法播放视频，请使用下载链接。</video><a class="video-download" href="${safeHref(track.path)}" download>下载视频 ↓</a></div>`).join("");
    const issueCount = data.issues.filter(issue => issue.lesson_id === lesson.id).length;
    const previous = lessons[index - 1], next = lessons[index + 1];
    $("reading-area").innerHTML = `<article><header class="article-header"><p class="article-kicker">${escape(lesson.section || data.title)}</p><h2>${escape(lesson.title)}</h2><div class="article-meta"><span>第 ${index + 1} / ${lessons.length} 讲</span><span class="status${lesson.imported ? "" : " pending"}">${lesson.imported ? "正文已保存" : "正文未导入"}</span>${lesson.audio.length ? `<span>本地音频 ${lesson.audio.length} 段</span>` : ""}${lesson.video.length ? `<span>本地视频 ${lesson.video.length} 段</span>` : ""}</div></header>${audio ? `<section class="audio-area" aria-label="本讲音频">${audio}</section>` : ""}${video ? `<section class="video-area" aria-label="本讲视频">${video}</section>` : ""}${lesson.imported ? `<div class="article-body">${lesson.html}</div>` : '<div class="empty-state"><h2>本讲正文尚未导入</h2><p>目前只有课程目录记录；正文、图片、音频和视频仍需从课程来源保存。</p></div>'}${issueCount ? `<p class="import-notice">本讲有 ${issueCount} 项素材或源文件未保存完整，详见 web/build-report.json。</p>` : ""}${files ? `<div class="article-files">${files}</div>` : ""}<nav class="article-nav" aria-label="前后课程"><div>${previous ? `<a href="#lesson=${encodeURIComponent(previous.id)}"><small>← 上一讲</small>${escape(previous.title)}</a>` : ""}</div><div>${next ? `<a href="#lesson=${encodeURIComponent(next.id)}"><small>下一讲 →</small>${escape(next.title)}</a>` : ""}</div></nav></article>`;
    attachSubtitles(lesson);
    $("lesson-position").textContent = `LESSON ${String(index + 1).padStart(2, "0")} / ${String(lessons.length).padStart(2, "0")}`;
    document.title = `${lesson.title} · ${data.title}`;
    try { localStorage.setItem("course-current-lesson:" + data.title, lesson.id); } catch {}
    renderList();
    if (changed) window.scrollTo({top:0, behavior:"instant"});
  }

  function fromHash() {
    const match = location.hash.match(/^#lesson=(.*)$/);
    let id;
    try { id = match ? decodeURIComponent(match[1]) : null; } catch { id = null; }
    if (!byId.has(id)) {
      try { id = localStorage.getItem("course-current-lesson:" + data.title); } catch {}
      if (!byId.has(id)) id = lessons[0]?.id;
    }
    renderLesson(id);
  }
  function closeMenu() { document.body.classList.remove("menu-open"); $("menu-toggle").setAttribute("aria-expanded", "false"); }
  $("search").addEventListener("input", renderList);
  $("menu-toggle").addEventListener("click", () => { const open = document.body.classList.toggle("menu-open"); $("menu-toggle").setAttribute("aria-expanded", String(open)); if (open) $("search").focus(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape") closeMenu(); });
  document.addEventListener("click", event => { if (document.body.classList.contains("menu-open") && !$("sidebar").contains(event.target) && !$("menu-toggle").contains(event.target)) closeMenu(); });
  $("lesson-list").addEventListener("click", event => { if (event.target.closest("a")) { closeMenu(); $("reader").focus({preventScroll:true}); } });
  for (const [id, delta] of [["font-smaller", -1], ["font-larger", 1]]) {
    $(id).addEventListener("click", () => { fontSize = Math.max(15, Math.min(24, fontSize + delta)); document.documentElement.style.setProperty("--reader-size", fontSize + "px"); try { localStorage.setItem("course-font-size", String(fontSize)); } catch {} });
  }
  $("print").addEventListener("click", () => window.print());
  window.addEventListener("hashchange", () => {
    if (location.hash.startsWith("#source-")) {
      let anchor;
      try { anchor = document.getElementById(decodeURIComponent(location.hash.slice(1))); } catch {}
      if (anchor) anchor.scrollIntoView({block:"start"});
      return;
    }
    fromHash();
  });
  fromHash();
})();
