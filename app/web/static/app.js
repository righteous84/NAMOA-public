/*
 * NAMOA GUI - minimal progressive enhancement (Sprint 6.12 + GUI/UX
 * Phases 1-5).
 *
 * All data is server-rendered from real application services; this
 * script only adds presentation behaviour:
 *   - a "refreshed at" note using the page render timestamp
 *   - client-side table filtering (name/path text match)
 *   - confirmation before starting a scan
 *   - recommendation selection helpers (select-all / clear / count)
 *   - inline approval confirmation (dashboard cards + opportunity
 *     detail), posting through the existing approval boundary
 *   - the persistent right-side notification stack (Phase 4), which
 *     fetches the active notifications, renders them, and handles
 *     individual dismissal and "Clear all"
 *   - the folder browser + background scan progress (Phase 5), which
 *     polls the durable scan status and shows honest progress with an
 *     approximate ETA and rotating plain-text humour
 *
 * It performs NO intelligence computation, no ranking, no validity
 * or currentness logic, no savings estimation, and no persistence
 * access. Data shown is whatever the authoritative reads return;
 * every page is served with Cache-Control: no-store.
 */

(function () {
  "use strict";

  var REFRESHED_AT = document.body.getAttribute("data-refreshed-at");

  // Theme switch: explicit choice persisted in localStorage,
  // independent of all profile and application data. The
  // default (no stored choice) is the Dark theme.
  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }

  var themeToggle = document.getElementById("theme-toggle");

  function syncThemeLabel() {
    if (themeToggle) {
      themeToggle.textContent =
        currentTheme() === "light" ? "Dark mode" : "Light mode";
    }
  }

  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      var next = currentTheme() === "light" ? "dark" : "light";
      try { localStorage.setItem("namoa-theme", next); } catch (e) {}
      document.documentElement.setAttribute("data-theme", next);
      syncThemeLabel();
    });
  }

  syncThemeLabel();

  // Top-right utility menu: cog toggles a compact dropdown with
  // Settings (existing page) and About (overlay). No navigation
  // framework; plain toggle plus outside-click and Escape.
  var cog = document.getElementById("utility-cog");
  var dropdown = document.getElementById("utility-dropdown");

  function setMenu(open) {
    if (!cog || !dropdown) { return; }
    dropdown.hidden = !open;
    cog.setAttribute("aria-expanded", open ? "true" : "false");
  }

  if (cog && dropdown) {
    cog.addEventListener("click", function (event) {
      event.stopPropagation();
      setMenu(dropdown.hidden);
    });

    document.addEventListener("click", function (event) {
      if (!dropdown.hidden && !dropdown.contains(event.target)) {
        setMenu(false);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !dropdown.hidden) {
        setMenu(false);
        cog.focus();
      }
    });
  }

  // About modal: centred overlay over the current page. Mirrors
  // the approve-modal focus handling (save/restore, Escape).
  var aboutModal = document.getElementById("about-modal");
  var aboutBtn = document.getElementById("utility-about");
  var aboutOkay = document.getElementById("about-modal-okay");
  var aboutLastFocused = null;

  function closeAbout() {
    if (!aboutModal) { return; }
    aboutModal.hidden = true;
    if (aboutLastFocused) {
      aboutLastFocused.focus();
      aboutLastFocused = null;
    }
  }

  function openAbout() {
    if (!aboutModal) { return; }
    aboutLastFocused = document.activeElement;
    setMenu(false);
    aboutModal.hidden = false;
    if (aboutOkay) { aboutOkay.focus(); }
  }

  if (aboutBtn) {
    aboutBtn.addEventListener("click", openAbout);
  }

  if (aboutModal) {
    if (aboutOkay) {
      aboutOkay.addEventListener("click", closeAbout);
    }

    aboutModal.addEventListener("click", function (event) {
      if (event.target === aboutModal) {
        closeAbout();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !aboutModal.hidden) {
        closeAbout();
      }
    });
  }

  // Playful system-status phrases beside ONLINE. Original short
  // expressions only; personality, not status information (the
  // ONLINE indicator stays authoritative; mood text is
  // aria-hidden in markup).
  var MOOD_PHRASES = [
    "Systems nominal",
    "All systems go",
    "Everything is fine",
    "The monkeys are working",
    "Bananas accounted for",
    "Engines humming",
    "Optimisation engaged",
    "Nothing exploded",
    "Coffee levels acceptable",
    "We appear to be operational",
    "Running smoothly",
    "All circuits behaving",
    "The hamsters approve",
    "Still crunching numbers",
    "The machinery lives",
    "Absolutely nominal",
    "Processing without incident",
    "Intelligence online",
    "Optimisation underway",
    "The bananas are secure",
    "Purring like a server room",
    "Codecs cooperating",
    "Pixels behaving themselves",
    "Bitrates under control",
    "No dramas detected",
    "Humming along nicely",
    "All green over here",
    "Quietly excellent",
    "Doing the thing",
    "On the job",
    "Wide awake",
    "Fully caffeinated",
    "Zero complaints filed",
    "Nominal-ish",
    "Suspiciously smooth",
    "Operating within parameters",
    "Parameters nominal",
    "Vibes nominal",
    "Entropy declining",
    "Order prevailing",
    "Chaos contained",
    "Gremlins on break",
    "Goblins appeased",
    "Trolls unbothered",
    "Dragons napping",
    "Wizards consulted",
    "The oracle nods",
    "Stars aligned-ish",
    "Tea levels adequate",
    "Biscuits located",
    "Snacks secured",
    "Morale acceptable",
    "Hamster wheel spinning",
    "Gerbil oversight active",
    "Squirrel audit passed",
    "Pigeon post on time",
    "Owl shift covered",
    "Raccoon quality control",
    "Fox supervision noted",
    "Badger approval granted",
    "Otter enthusiasm high",
    "Penguin formality observed",
    "Giraffe oversight tall",
    "Elephant memory intact",
    "Ant teamwork exemplary",
    "Bee productivity buzzing",
    "Butterfly effects minimal",
    "Moth attraction managed",
    "Firefly lighting adequate",
    "Cricket commentary lively",
    "Frog chorus harmonious",
    "Turtle pace steady",
    "Snail mail declined",
    "Slug urgency noted",
    "Worms turning smoothly",
    "Spider webbing tidy",
    "Ant farm thriving",
    "Beehive humming",
    "Coral policies stable",
    "Tide tables normal",
    "Wind conditions fair",
    "Solar input steady",
    "Lunar cycle tracked",
    "Tides punctual",
    "Weather inside: fine",
    "Thermals comfortable",
    "Humidity unbothered",
    "Pressure stable",
    "Altitude appropriate",
    "Mines swept",
    "All clear",
    "Radar quiet",
    "Sonar friendly",
    "Lidar polite",
    "Sensors flattered",
    "Dials confident",
    "Gauges smug",
    "Needles steady",
    "Switches willing",
    "Buttons responsive",
    "Knobs turned correctly",
    "Levers oiled",
    "Gears meshing",
    "Belts tightened",
    "Bolts torqued",
    "Pipes unclogged",
    "Filters fresh",
    "Coolant cool",
    "Fuel efficient",
    "Batteries optimistic",
    "Cables untangled",
    "Packets delivered",
    "Pixels plump",
    "Frames framed",
    "Cuts clean",
    "Transitions smooth",
    "Encodes encoding",
    "Muxing along",
    "Streams streaming",
    "Caches warm",
    "Queues orderly",
    "Jobs jobbing",
    "Workers working",
    "Logs logged",
    "Monitors monitoring",
    "Dashboards dashing"
  ];

  var moodEl = document.getElementById("namoa-mood");
  var moodIndex = -1;
  var reduceMotion = false;

  try {
    reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
  } catch (e) {}

  function nextMood() {
    if (!moodEl || !MOOD_PHRASES.length) { return; }
    var next;
    do {
      next = Math.floor(Math.random() * MOOD_PHRASES.length);
    } while (next === moodIndex && MOOD_PHRASES.length > 1);
    moodIndex = next;
    var text = MOOD_PHRASES[next];

    if (reduceMotion) {
      moodEl.textContent = text;
      return;
    }

    moodEl.classList.add("mood-fade");
    window.setTimeout(function () {
      moodEl.textContent = text;
      moodEl.classList.remove("mood-fade");
    }, 400);
  }

  if (moodEl) {
    nextMood();
    window.setInterval(nextMood, 9000);
  }

  if (REFRESHED_AT) {
    var note = document.getElementById("refresh-note");
    if (note) {
      note.textContent = "Rendered " + REFRESHED_AT;
    }
  }

  var filterInputs = document.querySelectorAll(".filter-input");

  // Sprint 15: reusable folder browsers. Each
  // `.folder-browser[data-target]` block is independent:
  // Browse toggles it, Up/entries navigate via the single
  // /api/fs/browse endpoint, and Use this folder writes
  // the chosen directory into the target input (appending
  // a line for multi-value fields). Read-only navigation;
  // nothing is created or changed on disk. Row Browse
  // buttons retarget a section browser onto their own
  // input through window.__namoaOpenBrowser.
  var browserLoaders = {};

  function wireBrowser(browser) {
    var uid = browser.id.replace("folder-browser-", "");
    var toggle = document.querySelector('.js-browse-toggle[data-browser="' + uid + '"]');
    var list = document.getElementById("folder-list-" + uid);
    var fileList = document.getElementById("file-list-" + uid);
    var wantFiles = browser.getAttribute("data-files") === "1";
    var current = document.getElementById("folder-current-" + uid);
    var errorBox = document.getElementById("folder-error-" + uid);
    var mode = browser.getAttribute("data-mode") || "set";
    var state = { current: null, parent: null };

    function target() {
      return document.getElementById(browser.getAttribute("data-target"));
    }

    function load(path) {
      if (list) { list.textContent = ""; }
      if (fileList) { fileList.textContent = ""; }
      if (errorBox) { errorBox.textContent = ""; }
      var url = "/api/fs/browse";
      var query = [];
      if (path) { query.push("path=" + encodeURIComponent(path)); }
      if (wantFiles) { query.push("files=1"); }
      if (query.length) { url += "?" + query.join("&"); }
      fetch(url, { headers: { "Accept": "application/json" } })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          state.current = data.current || null;
          state.parent = data.parent || null;
          if (current) { current.textContent = data.current || "/"; }
          if (errorBox) { errorBox.textContent = data.error || ""; }
          if (!list) { return; }
          list.textContent = "";
          (data.entries || []).forEach(function (entry) {
            var li = document.createElement("li");
            var btn = document.createElement("button");
            btn.type = "button";
            btn.textContent = entry.name + "/";
            btn.addEventListener("click", function () { load(entry.path); });
            li.appendChild(btn);
            list.appendChild(li);
          });
          if (!(data.entries || []).length && !(data.error || "")) {
            var empty = document.createElement("li");
            var span = document.createElement("span");
            span.className = "folder-error";
            span.textContent = wantFiles && (data.files || []).length
              ? "No further subdirectories here. Pick a file below."
              : "No subdirectories here.";
            empty.appendChild(span);
            list.appendChild(empty);
          }
          if (fileList) {
            fileList.textContent = "";
            (data.files || []).forEach(function (file) {
              var li = document.createElement("li");
              li.className = "file-row";
              var name = document.createElement("span");
              name.className = "file-name";
              name.textContent = file.name;
              var kind = document.createElement("span");
              kind.className = "badge unknown";
              kind.textContent = "video";
              var pick = document.createElement("button");
              pick.type = "button";
              pick.className = "btn small ghost js-file-select";
              pick.textContent = "Select";
              pick.setAttribute(
                "aria-label", "Select file " + file.name
              );
              pick.addEventListener("click", function () {
                var dest = target();
                if (!dest || !("value" in dest)) { return; }
                dest.value = file.path;
                browser.hidden = true;
                if (toggle) {
                  toggle.setAttribute("aria-expanded", "false");
                }
                dest.focus();
              });
              li.appendChild(name);
              li.appendChild(kind);
              li.appendChild(pick);
              fileList.appendChild(li);
            });
            if (wantFiles && !(data.files || []).length && !(data.error || "")) {
              var none = document.createElement("li");
              var spanNone = document.createElement("span");
              spanNone.className = "folder-error";
              spanNone.textContent = "No media files in this folder.";
              none.appendChild(spanNone);
              fileList.appendChild(none);
            }
            if (data.truncated) {
              var more = document.createElement("li");
              var spanMore = document.createElement("span");
              spanMore.className = "folder-error";
              spanMore.textContent =
                "Showing the first media files only; "
                + "type the rest of the name if needed.";
              more.appendChild(spanMore);
              fileList.appendChild(more);
            }
          }
        })
        .catch(function () {
          if (errorBox) { errorBox.textContent = "Could not load this folder."; }
        });
    }

    function open(inputId) {
      if (inputId) { browser.setAttribute("data-target", inputId); }
      browser.hidden = false;
      if (toggle) { toggle.setAttribute("aria-expanded", "true"); }
      load(state.current);
    }

    browserLoaders[uid] = open;

    if (toggle) {
      toggle.addEventListener("click", function () {
        if (browser.hidden) { open(null); }
        else {
          browser.hidden = true;
          toggle.setAttribute("aria-expanded", "false");
        }
      });
    }

    browser.querySelectorAll(".js-folder-up").forEach(function (btn) {
      btn.addEventListener("click", function () { load(state.parent); });
    });
    browser.querySelectorAll(".js-folder-close").forEach(function (btn) {
      btn.addEventListener("click", function () {
        browser.hidden = true;
        if (toggle) { toggle.setAttribute("aria-expanded", "false"); }
      });
    });
    browser.querySelectorAll(".js-folder-select").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var dest = target();
        if (!state.current || !dest) { return; }
        if (mode === "append" && "value" in dest) {
          var existing = dest.value.trim();
          dest.value = existing ? existing + "\n" + state.current : state.current;
        } else if (dest && "value" in dest) {
          dest.value = state.current;
        }
        browser.hidden = true;
        if (toggle) { toggle.setAttribute("aria-expanded", "false"); }
        dest.focus();
      });
    });
  }

  document.querySelectorAll(".folder-browser[data-target]").forEach(wireBrowser);

  window.__namoaOpenBrowser = function (uid, inputId) {
    var open = browserLoaders[uid];
    if (open) { open(inputId); }
  };
  // Sprint 15: structured profile rows. Add clones the
  // last row of a repeat group with cleared values;
  // Remove drops a row but keeps at least one. Row
  // Browse buttons retarget the section browser onto
  // that row's input before opening it.
  function clearRowValues(row, tag) {
    row.querySelectorAll("input, select, textarea").forEach(function (field) {
      if (field.tagName === "SELECT") { field.selectedIndex = 0; }
      else { field.value = ""; }
      field.removeAttribute("id");
    });
    row.querySelectorAll(".js-row-browse").forEach(function (btn) {
      var input = row.querySelector('input[type="text"]');
      if (input && tag) {
        input.id = tag + "-" + Date.now().toString(36);
        btn.setAttribute("data-input", input.id);
      } else {
        btn.removeAttribute("data-input");
      }
    });
  }

  [["root-add", "root-rows", "root"], ["source-add", "source-rows", "source"], ["cat-add", "cat-rows", null], ["map-add", "map-rows", null], ["sig-add", "sig-rows", null], ["cert-add", "cert-rows", null], ["coll-add", "coll-rows", null], ["rule-add", "rule-rows", null]].forEach(function (triple) {
    var addBtn = document.getElementById(triple[0]);
    var container = document.getElementById(triple[1]);
    if (!addBtn || !container) { return; }
    addBtn.addEventListener("click", function () {
      var rows = container.querySelectorAll("[data-repeat]");
      var last = rows[rows.length - 1];
      if (!last) { return; }
      var clone = last.cloneNode(true);
      clearRowValues(clone, triple[2]);
      container.appendChild(clone);
    });
  });

  // Sprint 15 correction: Generate Library Root Tags
  // fills only blank root-tag inputs with the next free
  // positional default ({root}, {root2}, ...), skipping
  // tags already present. Custom aliases are never
  // overwritten; the server re-validates on save.
  var rootTagsBtn = document.getElementById("root-tags-generate");
  var rootRows = document.getElementById("root-rows");
  if (rootTagsBtn && rootRows) {
    rootTagsBtn.addEventListener("click", function () {
      var taken = {};
      rootRows.querySelectorAll(".js-root-alias").forEach(function (field) {
        var value = (field.value || "").trim();
        if (value) { taken[value] = true; }
      });
      var counter = 0;
      function nextDefault() {
        var name;
        do {
          name = counter === 0 ? "root" : "root" + (counter + 1);
          counter += 1;
        } while (taken[name]);
        taken[name] = true;
        return name;
      }
      rootRows.querySelectorAll(".js-root-alias").forEach(function (field) {
        if (!(field.value || "").trim()) {
          field.value = nextDefault();
        }
      });
    });
  }

  // Sprint 15 identification: token picker inserts
  // the token at the cursor of the extended naming
  // field; the extended block only expands when the
  // extended radio is selected.
  document.addEventListener("click", function (event) {
    var token = event.target.closest
      ? event.target.closest(".js-token")
      : null;
    if (token) {
      var field = document.getElementById("filename-extended");
      var value = token.getAttribute("data-token") || "";
      if (field && value) {
        var start = field.selectionStart || field.value.length;
        var end = field.selectionEnd || field.value.length;
        field.value = field.value.slice(0, start) + value
          + field.value.slice(end);
        try { field.focus(); } catch (e) {}
      }
      return;
    }
  });

  function syncExtendedBlock() {
    var block = document.getElementById("filename-extended-block");
    if (!block) { return; }
    var selected = document.querySelector(
      'input[name="filename_mode"]:checked'
    );
    var show = !selected || selected.value === "extended";
    block.style.display = show ? "" : "none";
  }

  document.addEventListener("change", function (event) {
    if (event.target && event.target.name === "filename_mode") {
      syncExtendedBlock();
    }
  });

  syncExtendedBlock();

  // Organisation rule ordering: rules are
  // checked top to bottom, first match wins. Up
  // and Down move the row; order is saved with
  // the form.
  document.addEventListener("click", function (event) {
    var up = event.target.closest
      ? event.target.closest(".js-row-up")
      : null;
    var down = !up && event.target.closest
      ? event.target.closest(".js-row-down")
      : null;
    var btn = up || down;
    if (!btn) { return; }
    var row = btn.closest("[data-repeat]");
    if (!row || !row.parentElement) { return; }
    if (up && row.previousElementSibling) {
      row.parentElement.insertBefore(
        row, row.previousElementSibling
      );
    } else if (
      down && row.nextElementSibling
    ) {
      row.parentElement.insertBefore(
        row.nextElementSibling, row
      );
    }
  });

  // Organisation rules: target dropdowns always
  // reflect the current Categories list. Categories
  // are authoritative; the whole editor saves as
  // one transaction, so options derive from the
  // in-memory rows before persistence.
  function currentCategoryNames() {
    var names = [];
    document.querySelectorAll(
      '#cat-rows input[name="cat_name"]'
    ).forEach(function (field) {
      var value = (field.value || "").trim();
      if (value && names.indexOf(value) === -1) {
        names.push(value);
      }
    });
    return names;
  }

  function syncRuleTargets() {
    var catInputs = document.querySelectorAll(
      '#cat-rows input[name="cat_name"]'
    );
    if (!catInputs.length) { return; }
    var names = currentCategoryNames();
    document.querySelectorAll(
      "select.js-rule-target"
    ).forEach(function (select) {
      var current = select.value;
      while (select.firstChild) {
        select.removeChild(select.firstChild);
      }
      names.forEach(function (name) {
        var option = document.createElement("option");
        option.value = name;
        option.textContent = name;
        if (name === current) {
          option.selected = true;
        }
        select.appendChild(option);
      });
      if (current && names.indexOf(current) === -1) {
        var missing = document.createElement("option");
        missing.value = current;
        missing.textContent = current + " (removed)";
        missing.selected = true;
        select.appendChild(missing);
      }
    });
  }

  document.addEventListener("input", function (event) {
    if (
      event.target &&
      event.target.name === "cat_name"
    ) {
      syncRuleTargets();
    }
  });

  document.addEventListener("click", function (event) {
    var hit = event.target.closest
      ? event.target.closest(
        "#cat-add, #rule-add, .js-row-remove"
      )
      : null;
    if (hit) {
      window.setTimeout(syncRuleTargets, 0);
    }
  });

  syncRuleTargets();

  // What-If input mode: Media ID or File path,
  // never both. The inactive input is disabled so
  // it cannot submit.
  function syncWhatifMode() {
    var checked = document.querySelector(
      'input[name="input_mode"]:checked'
    );
    var media = document.getElementById("whatif-media-id");
    var path = document.getElementById("whatif-file-path");
    var browse = document.getElementById("whatif-browse");
    var mediaCard = document.getElementById("whatif-media-card");
    var fileCard = document.getElementById("whatif-file-card");
    var extended = document.getElementById(
      "whatif-extended-block"
    );
    var template = document.getElementById(
      "whatif-template-block"
    );
    var mode = checked ? checked.value : "media";
    var useFile = (mode === "file");
    if (media) {
      media.disabled = useFile;
      if (useFile) { media.value = ""; }
    }
    if (path) {
      path.disabled = !useFile;
      if (!useFile) { path.value = ""; }
    }
    if (browse) { browse.disabled = !useFile; }
    if (mediaCard) {
      mediaCard.classList.toggle("input-card-active", !useFile);
      mediaCard.classList.toggle("input-card-inactive", useFile);
    }
    if (fileCard) {
      fileCard.classList.toggle("input-card-active", useFile);
      fileCard.classList.toggle("input-card-inactive", !useFile);
    }
    syncWhatifNaming();
  }

  function syncWhatifNaming() {
    var selected = document.querySelector(
      'input[name="run_mode"]:checked'
    );
    var mode = selected ? selected.value : "profile";
    var extended = document.getElementById(
      "whatif-extended-block"
    );
    var template = document.getElementById(
      "whatif-template-block"
    );
    if (extended) {
      extended.style.display =
        (mode === "extended") ? "" : "none";
    }
    if (template) {
      template.style.display =
        (mode === "template") ? "" : "none";
    }
  }

  document.addEventListener("click", function (event) {
    var open = event.target.closest
      ? event.target.closest(".js-browse-open")
      : null;
    if (open) {
      var uid = open.getAttribute("data-browser");
      var toggle = uid
        ? document.querySelector(
          '.js-browse-toggle[data-browser="' + uid + '"]'
        )
        : null;
      if (toggle) { toggle.click(); }
      return;
    }
  });

  document.addEventListener("change", function (event) {
    if (
      event.target &&
      (event.target.name === "input_mode" ||
        event.target.name === "run_mode")
    ) {
      syncWhatifMode();
    }
  });

  syncWhatifMode();

  // Directory sampler loading state: immediate
  // busy feedback, duplicate-submit guard, and a
  // rotation of short original messages under the
  // real progress text (which always stays).
  var SAMPLER_HUMOUR = [
    "Checking the evidence. No plot twists yet.",
    "The director's cut is loading.",
    "Searching for something worth organising.",
    "Checking the cast list.",
    "Looking for the good stuff."
  ];

  var samplerForm = document.getElementById("sampler-form");

  if (samplerForm) {
    samplerForm.addEventListener("submit", function () {
      var panel = document.getElementById("sampler-loading");
      var submit = document.getElementById("sampler-submit");
      var funny = document.getElementById("sampler-humour");
      if (submit) { submit.disabled = true; }
      if (panel) { panel.hidden = false; }
      if (funny && SAMPLER_HUMOUR.length) {
        var pick = Math.floor(
          Math.random() * SAMPLER_HUMOUR.length
        );
        funny.textContent = SAMPLER_HUMOUR[pick];
      }
    });
  }

  // Form feedback: bring save errors and save
  // confirmations into view. A successful save never
  // leaves a previous error visible because the page
  // only ever renders one of the two panels.
  (function () {
    var target = document.getElementById("profile-form-error")
      || document.getElementById("profile-save-success")
      || document.querySelector(".error-panel[role='alert']");
    if (!target) { return; }
    try { target.scrollIntoView({block: "start"}); } catch (e) {}
    try { target.focus({preventScroll: true}); } catch (e) {}
  })();

  document.addEventListener("click", function (event) {
    var remove = event.target.closest ? event.target.closest(".js-row-remove") : null;
    if (remove) {
      var row = remove.closest("[data-repeat]");
      var container = row ? row.parentElement : null;
      if (row && container && container.querySelectorAll("[data-repeat]").length > 1) {
        row.remove();
      } else if (row) {
        clearRowValues(row, null);
      }
      return;
    }
    var browse = event.target.closest ? event.target.closest(".js-row-browse") : null;
    if (browse) {
      window.__namoaOpenBrowser(
        browse.getAttribute("data-browser"),
        browse.getAttribute("data-input")
      );
    }
  });

  // Sprint 15: credential Show/Hide toggles. Each toggle
  // only affects its paired password input and never
  // touches stored credentials (which are never rendered).
  document.querySelectorAll(".js-reveal").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var targetId = btn.getAttribute("data-target");
      var input = targetId
        ? document.getElementById(targetId)
        : null;
      if (!input) { return; }
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      btn.textContent = show ? "Hide" : "Show";
      btn.setAttribute("aria-pressed", show ? "true" : "false");
    });
  });

  filterInputs.forEach(function (input) {
    input.addEventListener("input", function () {
      var query = (input.value || "").toLowerCase().trim();
      var tableWrap = input.closest(".card").querySelector(".table-wrap");
      if (!tableWrap) { return; }

      var rows = tableWrap.querySelectorAll("tbody tr");

      rows.forEach(function (row) {
        var haystack = (row.textContent || "").toLowerCase();
        row.style.display = query && haystack.indexOf(query) === -1
          ? "none"
          : "";
      });
    });
  });

  // Sprint 11 selection helpers (presentation only).
  var selectionForm = document.getElementById("selection-form");

  if (selectionForm) {
    var selectAll = document.getElementById("select-all");
    var clearButton = document.getElementById("clear-selection");
    var countNote = document.getElementById("selection-count");

    var items = function () {
      return Array.prototype.slice.call(
        selectionForm.querySelectorAll(".select-item")
      );
    };

    var updateCount = function () {
      if (!countNote) { return; }
      var checked = items().filter(function (box) {
        return box.checked;
      }).length;
      countNote.textContent = checked + " selected";
    };

    if (selectAll) {
      selectAll.addEventListener("change", function () {
        items().forEach(function (box) {
          box.checked = selectAll.checked;
        });
        updateCount();
      });
    }

    selectionForm.addEventListener("change", function (event) {
      if (!event.target.classList.contains("select-item")) { return; }
      updateCount();
    });

    if (clearButton) {
      clearButton.addEventListener("click", function () {
        items().forEach(function (box) {
          box.checked = false;
        });
        if (selectAll) { selectAll.checked = false; }
        updateCount();
      });
    }

    updateCount();

    selectionForm.addEventListener("submit", function (event) {
      var anyChecked = items().some(function (box) {
        return box.checked;
      });

      if (!anyChecked) {
        event.preventDefault();
      }
    });
  }

  // Phase 1/3: approval confirmation modal. The confirm step never
  // starts execution: the POST goes through the existing approval
  // boundary, which only creates approved job(s) in the queue.

  var approveModal = document.getElementById("approve-modal");
  var approveForm = document.getElementById("approve-modal-form");
  var approveFields = document.getElementById("approve-modal-fields");
  var approveMessage = document.getElementById("approve-modal-message");
  var approveCancel = document.getElementById("approve-modal-cancel");

  var lastFocused = null;

  function closeApproveModal() {
    if (!approveModal) { return; }
    approveModal.hidden = true;
    if (lastFocused) {
      lastFocused.focus();
      lastFocused = null;
    }
  }

  function openApproveModal(message) {
    if (!approveModal || !approveForm) { return; }

    lastFocused = document.activeElement;

    if (approveMessage) {
      approveMessage.textContent = message;
    }

    // NOTE: the form action and hidden fields are prepared by the
    // callers (approveSingle / approveSelected) BEFORE this opens the
    // modal. They must not be reset here, or the confirmation would
    // submit to the current URL (e.g. "/") with no selection.

    approveModal.hidden = false;

    var confirmBtn = approveForm.querySelector('button[type="submit"]');
    if (confirmBtn) { confirmBtn.focus(); }
  }

  function setupModalActions() {
    if (!approveModal) { return; }

    if (approveCancel) {
      approveCancel.addEventListener("click", closeApproveModal);
    }

    approveModal.addEventListener("click", function (event) {
      if (event.target === approveModal) {
        closeApproveModal();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !approveModal.hidden) {
        closeApproveModal();
      }
    });
  }

  function addHiddenField(name, value) {
    if (!approveFields) { return; }
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    approveFields.appendChild(input);
  }

  function approveSingle(mediaId, name) {
    if (!approveForm) { return; }
    approveForm.setAttribute(
      "action",
      "/opportunities/" + mediaId + "/approve"
    );
    if (approveFields) { approveFields.textContent = ""; }
    openApproveModal(
      "Approve the optimisation for " + (name || ("media " + mediaId)) +
      "? This creates an approved job in the optimisation queue. " +
      "Nothing will run until you start it."
    );
  }

  function approveSelected(mediaIds, label) {
    if (!approveForm) { return; }
    approveForm.setAttribute(
      "action",
      "/opportunities/confirm-acceptance"
    );
    if (approveFields) { approveFields.textContent = ""; }
    mediaIds.forEach(function (id) {
      addHiddenField("selected", String(id));
    });
    openApproveModal(label);
  }

  document.querySelectorAll(".js-approve-single").forEach(function (btn) {
    btn.addEventListener("click", function () {
      approveSingle(
        btn.getAttribute("data-media-id"),
        btn.getAttribute("data-name") || ""
      );
    });
  });

  setupModalActions();

  // Dashboard rejection confirmation modal. Mirrors the approval
  // modal pattern: the POST goes to the dashboard rejection
  // endpoints, which refuse the currently active propositions
  // through the existing standing-decision semantics.

  var rejectModal = document.getElementById("reject-modal");
  var rejectForm = document.getElementById("reject-modal-form");
  var rejectFields = document.getElementById("reject-modal-fields");
  var rejectMessage = document.getElementById("reject-modal-message");
  var rejectCancel = document.getElementById("reject-modal-cancel");

  var rejectLastFocused = null;

  function closeRejectModal() {
    if (!rejectModal) { return; }
    rejectModal.hidden = true;
    if (rejectLastFocused) {
      rejectLastFocused.focus();
      rejectLastFocused = null;
    }
  }

  function openRejectModal(message) {
    if (!rejectModal || !rejectForm) { return; }

    rejectLastFocused = document.activeElement;

    if (rejectMessage) {
      rejectMessage.textContent = message;
    }

    rejectModal.hidden = false;

    var confirmBtn = rejectForm.querySelector('button[type="submit"]');
    if (confirmBtn) { confirmBtn.focus(); }
  }

  function addRejectField(name, value) {
    if (!rejectFields) { return; }
    var input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    rejectFields.appendChild(input);
  }

  function rejectSingle(mediaId, name) {
    if (!rejectForm) { return; }
    rejectForm.setAttribute(
      "action",
      "/opportunities/" + mediaId + "/reject"
    );
    if (rejectFields) { rejectFields.textContent = ""; }
    openRejectModal(
      "Are you sure you wish to reject this optimisation? " +
      "This will reject the current optimisation recommendations " +
      "for " + (name || ("media " + mediaId)) + " and remove them " +
      "from your active recommendations. They will remain " +
      "available in history."
    );
  }

  function rejectSelected(mediaIds) {
    if (!rejectForm) { return; }
    rejectForm.setAttribute(
      "action",
      "/opportunities/reject-selected"
    );
    if (rejectFields) { rejectFields.textContent = ""; }
    mediaIds.forEach(function (id) {
      addRejectField("selected", String(id));
    });
    openRejectModal(
      "Are you sure you wish to reject these " + mediaIds.length +
      " optimisations? This will reject the current optimisation " +
      "recommendations represented by the selected files and " +
      "remove them from your active recommendations. They will " +
      "remain available in history."
    );
  }

  document.querySelectorAll(".js-reject-single").forEach(function (btn) {
    btn.addEventListener("click", function () {
      rejectSingle(
        btn.getAttribute("data-media-id"),
        btn.getAttribute("data-name") || ""
      );
    });
  });

  var rejectSelectedBtn = document.querySelector(".js-reject-selected");
  if (rejectSelectedBtn) {
    rejectSelectedBtn.addEventListener("click", function () {
      var ids = selectedMediaIds();
      if (!ids.length) {
        updateRecSelectionCount();
        return;
      }
      rejectSelected(ids);
    });
  }

  if (rejectModal) {
    if (rejectCancel) {
      rejectCancel.addEventListener("click", closeRejectModal);
    }

    rejectModal.addEventListener("click", function (event) {
      if (event.target === rejectModal) {
        closeRejectModal();
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && !rejectModal.hidden) {
        closeRejectModal();
      }
    });
  }

  // Dashboard selection + bulk approval.

  var recCards = document.querySelectorAll(".rec-card[data-media-id]");
  var recSelectAll = document.getElementById("rec-select-all");
  var recCount = document.getElementById("rec-selection-count");

  function selectedMediaIds() {
    var ids = [];
    document.querySelectorAll(".rec-select-box:checked").forEach(function (box) {
      ids.push(box.value);
    });
    return ids;
  }

  function allMediaIds() {
    var ids = [];
    document.querySelectorAll(".rec-select-box").forEach(function (box) {
      ids.push(box.value);
    });
    return ids;
  }

  function updateRecSelectionCount() {
    if (!recCount) { return; }
    var n = selectedMediaIds().length;
    recCount.textContent = n + " selected";
  }

  if (recSelectAll) {
    recSelectAll.addEventListener("change", function () {
      document.querySelectorAll(".rec-select-box").forEach(function (box) {
        box.checked = recSelectAll.checked;
      });
      updateRecSelectionCount();
    });
  }

  recCards.forEach(function (card) {
    var box = card.querySelector(".rec-select-box");
    if (box) {
      box.addEventListener("change", updateRecSelectionCount);
    }
  });

  var approveSelectedBtn = document.querySelector(".js-approve-selected");
  if (approveSelectedBtn) {
    approveSelectedBtn.addEventListener("click", function () {
      var ids = selectedMediaIds();
      if (!ids.length) {
        updateRecSelectionCount();
        return;
      }
      approveSelected(
        ids,
        "Confirm approval of " + ids.length + " selected " +
        "optimisation(s)? Approval adds them to the optimisation " +
        "queue. Nothing will run until you start it."
      );
    });
  }

  var approveAllBtn = document.querySelector(".js-approve-all");
  if (approveAllBtn) {
    approveAllBtn.addEventListener("click", function () {
      var ids = allMediaIds();
      if (!ids.length) { return; }
      approveSelected(
        ids,
        "Confirm approval of " + ids.length + " optimisation(s)? " +
        "Approval adds them to the optimisation queue. Nothing will " +
        "run until you start it."
      );
    });
  }

  updateRecSelectionCount();

  // ---------------------------------------------------------
  // Phase 4: persistent notification stack
  // ---------------------------------------------------------

  function renderNotifications(list) {
    var panel = document.getElementById("notification-panel");
    if (!panel) { return; }

    panel.textContent = "";

    if (!list || !list.length) { return; }

    var clearAll = document.createElement("button");
    clearAll.type = "button";
    clearAll.className = "notification-clear";
    clearAll.textContent = "Clear all";
    clearAll.setAttribute("aria-label", "Dismiss all notifications");
    clearAll.addEventListener("click", function () {
      fetch("/api/notifications/dismiss-all", { method: "POST" })
        .then(refreshNotifications)
        .catch(function () {});
    });
    panel.appendChild(clearAll);

    list.forEach(function (n) {
      panel.appendChild(notificationNode(n));
    });
  }

  function notificationNode(n) {
    var node = document.createElement("div");
    node.className = "notification notification--" + (n.category || "information");

    var title = document.createElement("div");
    title.className = "notification-title";
    title.textContent = n.title || "";
    node.appendChild(title);

    if (n.message) {
      var msg = document.createElement("div");
      msg.className = "notification-message";
      msg.textContent = n.message;
      node.appendChild(msg);
    }

    var meta = document.createElement("div");
    meta.className = "notification-meta";

    var category = document.createElement("span");
    category.className = "notification-category";
    category.textContent = n.category_label || n.category || "";
    meta.appendChild(category);

    var links = n.links || {};
    var linkKeys = Object.keys(links);

    // Presentation-only labels for notification link targets.
    // The link destinations come from the backend unchanged.
    var linkLabels = {
      media: "Media",
      execution: "Execution",
      recommendation: "Recommendation",
      scan: "Scan"
    };

    if (linkKeys.length) {
      var linkWrap = document.createElement("span");
      linkWrap.className = "notification-links";
      linkKeys.forEach(function (key, index) {
        if (index > 0) {
          linkWrap.appendChild(document.createTextNode(" · "));
        }
        var a = document.createElement("a");
        a.href = links[key];
        a.textContent = linkLabels[key] || key;
        linkWrap.appendChild(a);
      });
      meta.appendChild(linkWrap);
    }

    var actions = document.createElement("span");
    actions.className = "notification-actions";

    var dismiss = document.createElement("button");
    dismiss.type = "button";
    dismiss.textContent = "Dismiss";
    dismiss.setAttribute(
      "aria-label",
      "Dismiss notification: " + (n.title || "")
    );
    dismiss.addEventListener("click", function () {
      fetch("/api/notifications/" + n.id + "/dismiss", { method: "POST" })
        .then(refreshNotifications)
        .catch(function () {});
    });
    actions.appendChild(dismiss);

    meta.appendChild(actions);
    node.appendChild(meta);

    return node;
  }

  function refreshNotifications() {
    return fetch("/api/notifications", {
      headers: { "Accept": "application/json" },
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        renderNotifications(data.notifications || []);
      })
      .catch(function () {});
  }

  // Poll calmly so new notifications appear without destroying old
  // ones (they persist server-side until dismissed).
  refreshNotifications();
  window.setInterval(refreshNotifications, 10000);

  // Footer health indicator: liveness of this same web
  // application, measured through the existing
  // read-only notifications endpoint. No separate
  // health system; a reachable JSON response means
  // ONLINE, anything else means OFFLINE. The DOM only
  // changes when the state itself changes.
  var healthRoot = document.getElementById("namoa-health");
  var healthText = document.getElementById("namoa-health-text");
  var healthState = "checking";

  function setHealth(state, label) {
    if (state === healthState) { return; }
    healthState = state;
    if (healthRoot) {
      healthRoot.setAttribute("data-state", state);
    }
    if (healthText) {
      healthText.textContent = label;
    }
  }

  function checkHealth() {
    if (!healthRoot) { return; }
    fetch("/api/notifications", {
      headers: { "Accept": "application/json" },
      cache: "no-store",
    })
      .then(function (response) {
        if (!response.ok) { throw new Error("unhealthy"); }
        return response.json();
      })
      .then(function () {
        setHealth("online", "ONLINE");
      })
      .catch(function () {
        setHealth("offline", "OFFLINE");
      });
  }

  checkHealth();
  window.setInterval(checkHealth, 20000);

  // Organisation scan handoff: when the page
  // carries a pre-populated path with autostart,
  // submit the normal scan form once so the
  // existing background scan flow runs without
  // retyping. The server still validates the path
  // and serialises scans as usual.
  try {
    var handoffPath = document.getElementById("scan-path");
    var handoffForm = document.getElementById("scan-form");
    var handoffProgress = document.getElementById(
      "scan-progress"
    );
    if (
      handoffForm && handoffPath &&
      handoffForm.getAttribute("data-autostart") === "1" &&
      handoffPath.value && !handoffProgress &&
      !window.__namoaScanAutostarted
    ) {
      window.__namoaScanAutostarted = true;
      handoffForm.submit();
    }
  } catch (e) {}

  // ---------------------------------------------------------
  // Phase 5: folder browser + background scan progress
  // ---------------------------------------------------------

  var scanForm = document.getElementById("scan-form");
  var scanPathInput = document.getElementById("scan-path");
  var browseToggle = document.getElementById("browse-toggle");
  var folderBrowser = document.getElementById("folder-browser");
  var folderList = document.getElementById("folder-list");
  var folderCurrent = document.getElementById("folder-current");
  var folderError = document.getElementById("folder-error");
  var folderUp = document.getElementById("folder-up");
  var folderSelect = document.getElementById("folder-select");
  var folderClose = document.getElementById("folder-close");

  var currentFolderPath = null;
  var currentParentPath = null;

  function browseURL(path) {
    var url = "/api/fs/browse";
    if (path) { url += "?path=" + encodeURIComponent(path); }
    return url;
  }

  function loadFolder(path) {
    if (folderList) { folderList.textContent = ""; }
    if (folderError) { folderError.textContent = ""; }

    fetch(browseURL(path), {
      headers: { "Accept": "application/json" },
    })
      .then(function (response) { return response.json(); })
      .then(function (data) {
        currentFolderPath = data.current || null;
        currentParentPath = data.parent || null;

        if (folderCurrent) {
          folderCurrent.textContent = data.current || "/";
        }

        if (folderError) {
          folderError.textContent = data.error || "";
        }

        if (!folderList) { return; }

        folderList.textContent = "";

        (data.entries || []).forEach(function (entry) {
          var li = document.createElement("li");
          var btn = document.createElement("button");
          btn.type = "button";
          btn.textContent = entry.name + "/";
          btn.addEventListener("click", function () {
            loadFolder(entry.path);
          });
          li.appendChild(btn);
          folderList.appendChild(li);
        });

        if (!(data.entries || []).length && !(data.error || "")) {
          var empty = document.createElement("li");
          var text = document.createElement("span");
          text.className = "folder-error";
          text.textContent = "No subdirectories here.";
          empty.appendChild(text);
          folderList.appendChild(empty);
        }
      })
      .catch(function () {
        if (folderError) {
          folderError.textContent = "Could not load this folder.";
        }
      });
  }

  if (browseToggle && folderBrowser) {
    browseToggle.addEventListener("click", function () {
      folderBrowser.hidden = !folderBrowser.hidden;
      if (!folderBrowser.hidden) {
        loadFolder(currentFolderPath);
      }
    });

    if (folderUp) {
      folderUp.addEventListener("click", function () {
        loadFolder(currentParentPath);
      });
    }

    if (folderClose) {
      folderClose.addEventListener("click", function () {
        folderBrowser.hidden = true;
      });
    }

    if (folderSelect && scanPathInput) {
      folderSelect.addEventListener("click", function () {
        if (!currentFolderPath) { return; }
        scanPathInput.value = currentFolderPath;
        folderBrowser.hidden = true;
      });
    }
  }

  if (scanForm) {
    scanForm.addEventListener("submit", function (event) {
      var path = scanPathInput ? scanPathInput.value.trim() : "";

      if (!path) {
        event.preventDefault();
        return;
      }

      var confirmed = window.confirm(
        "Start a background scan of:\n\n" +
        path +
        "\n\nNAMOA will scan this path and persist results in the " +
        "background. Missing files under the path are reconciled as " +
        "authoritative for this root. This can take a long time for " +
        "large libraries."
      );

      if (!confirmed) {
        event.preventDefault();
      }
    });
  }

  var SCAN_HUMOUR = [
    "Grab a coffee. Be done soon.",
    "Sit back and relax while we churn.",
    "The media goblins are counting your files.",
    "NAMOA is judging your compression choices.",
    "Cleaning up the digital cupboard.",
    "Counting approximately eleventy billion bytes.",
    "Measuring every frame for good measure.",
    "Feeding the bitrate calculator.",
    "Wrangling the codec herd.",
    "Asking the files how they're feeling today.",
    "Checking for sneaky HDR surprises.",
    "Sorting the cinematic haystack.",
    "Tuning the resolution microscope.",
    "Politely noting the remuxes that deserve a rest.",
    "Estimating how many bytes fit on a shelf.",
    "Consulting the great bitrate ledger.",
    "Making sure no film gets left behind.",
    "Wondering why that one file is so heavy.",
    "Brushing up on your library's life story.",
    "Almost there. Probably. Eventually."
  ];

  var scanProgress = document.getElementById("scan-progress");

  if (scanProgress) {
    startScanProgress(
      scanProgress.getAttribute("data-scan-id"),
      scanProgress.getAttribute("data-path") || ""
    );
  }

  function startScanProgress(scanId, scanPath) {
    scanProgress.textContent = "";

    var head = document.createElement("div");
    head.className = "scan-progress-head";

    var title = document.createElement("h3");
    title.textContent = "Scanning";

    var path = document.createElement("span");
    path.className = "scan-progress-path";
    path.id = "scan-progress-path";
    path.textContent = scanPath;

    head.appendChild(title);
    head.appendChild(path);

    var status = document.createElement("div");
    status.className = "scan-progress-status";
    status.id = "scan-progress-status";

    var bar = document.createElement("div");
    bar.className = "scan-progress-bar";
    bar.id = "scan-progress-bar";
    var fill = document.createElement("div");
    fill.className = "scan-progress-fill";
    fill.id = "scan-progress-fill";
    bar.appendChild(fill);

    var details = document.createElement("div");
    details.className = "scan-progress-details";
    details.id = "scan-progress-details";

    var humour = document.createElement("div");
    humour.className = "scan-progress-humour";
    humour.id = "scan-progress-humour";
    humour.textContent = SCAN_HUMOUR[0];

    scanProgress.appendChild(head);
    scanProgress.appendChild(status);
    scanProgress.appendChild(bar);
    scanProgress.appendChild(details);
    scanProgress.appendChild(humour);

    var humourIndex = 0;
    var humourTimer = null;

    var startHumour = function () {
      if (humourTimer) { return; }
      humourTimer = window.setInterval(function () {
        humourIndex = (humourIndex + 1) % SCAN_HUMOUR.length;
        humour.textContent = SCAN_HUMOUR[humourIndex];
      }, 6000);
    };

    var stopHumour = function () {
      if (humourTimer) {
        window.clearInterval(humourTimer);
        humourTimer = null;
      }
    };

    var formatElapsed = function (seconds) {
      if (seconds == null) { return ""; }
      var h = Math.floor(seconds / 3600);
      var m = Math.floor((seconds % 3600) / 60);
      var s = Math.floor(seconds % 60);
      if (h > 0) { return h + "h " + m + "m"; }
      if (m > 0) { return m + "m " + s + "s"; }
      return s + "s";
    };

    var render = function (s) {
      if (!s || !s.exists) { return; }

      document.getElementById("scan-progress-path").textContent =
        s.target_scope || scanPath;

      var statusEl = document.getElementById("scan-progress-status");
      var barEl = document.getElementById("scan-progress-bar");
      var fillEl = document.getElementById("scan-progress-fill");
      var detailsEl = document.getElementById("scan-progress-details");

      if (s.status === "failed") {
        barEl.classList.remove("indeterminate");
        fillEl.style.width = "0%";
        statusEl.className = "scan-progress-status scan-progress-error";
        statusEl.textContent = "Scan failed. " + (s.error_message || "");
        detailsEl.textContent = "";
        stopHumour();
        return;
      }

      if (s.status === "completed") {
        barEl.classList.remove("indeterminate");
        fillEl.style.width = "100%";
        statusEl.className = "scan-progress-status scan-progress-complete";
        statusEl.textContent =
          "Scan complete: " +
          (s.files_discovered || 0) + " files discovered, " +
          (s.files_analysed || 0) + " newly analysed, " +
          (s.files_reused || 0) + " reused, " +
          (s.files_skipped || 0) + " skipped, " +
          (s.files_failed || 0) + " failed.";
        detailsEl.textContent = "";
        stopHumour();
        return;
      }

      // Running.
      startHumour();

      if (s.phase === "discovering") {
        barEl.classList.add("indeterminate");
        statusEl.className = "scan-progress-status";
        statusEl.textContent = "Discovering files…";
        detailsEl.textContent =
          "Elapsed " + formatElapsed(s.elapsed_seconds) +
          " · no progress percentage yet (still discovering)";
        return;
      }

      barEl.classList.remove("indeterminate");
      var percent = s.percent != null ? s.percent : 0;
      fillEl.style.width = percent + "%";
      statusEl.className = "scan-progress-status";
      statusEl.textContent =
        "Analysing " + (s.files_processed || 0) + " of " +
        (s.files_discovered || 0) + " files (" + percent + "%)";

      var etaText = "";
      if (s.eta_seconds != null) {
        etaText =
          " · estimated remaining time (approx.) " +
          formatElapsed(s.eta_seconds);
      } else {
        etaText = " · estimated remaining time (approx.) not available yet";
      }

      detailsEl.textContent =
        "Elapsed " + formatElapsed(s.elapsed_seconds) + etaText;
    };

    var poll = function () {
      fetch("/api/scan/" + scanId, {
        headers: { "Accept": "application/json" },
      })
        .then(function (response) { return response.json(); })
        .then(render)
        .catch(function () {});
    };

    poll();
    window.setInterval(poll, 2000);
  }

  /* Sprint 15 productisation: background metadata sync progress.
   * Mirrors the Phase 5 scan pattern: poll the sync status
   * endpoint, render honest counters with a progress bar and
   * elapsed/ETA text, and rotate original cinematic humour
   * lines while work is in flight. Humour never replaces the
   * real numbers. Starts polling when a sync was just
   * started (data-running) or when a refresh finds one
   * already running.
   */

  var SYNC_HUMOUR = [
    "Scanning the evidence...",
    "Consulting the cast list...",
    "Checking who belongs in the sequel...",
    "Following the trail to the season finale...",
    "Digging through the archive...",
    "Putting the pieces together...",
    "Rolling the credits on this batch...",
    "Rewinding to double-check that scene...",
    "Matching extras to their directors...",
    "Cueing up the next reel of records...",
    "Reading the opening crawl for clues...",
    "Asking the supporting cast to line up...",
    "Comparing the director's cut...",
    "Waiting for the post-credits scene...",
    "Filing this one under must-organise..."
  ];

  var syncLive = document.getElementById("sync-live");

  function syncFormatTime(seconds) {
    if (seconds == null) { return ""; }
    var total = Math.floor(seconds);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    var pad = function (n) { return (n < 10 ? "0" : "") + n; };
    if (h > 0) { return h + ":" + pad(m) + ":" + pad(s); }
    return m + ":" + pad(s);
  }

  function syncCounterLine(snap) {
    var parts = [
      (snap.inspected || 0) + " inspected",
      (snap.matched || 0) + " matched",
      (snap.updated || 0) + " updated",
      (snap.unchanged || 0) + " unchanged",
      (snap.unmatched || 0) + " unmatched",
      (snap.needs_review || 0) + " need review",
      (snap.error_count || 0) + " errors"
    ];
    return parts.join(" · ");
  }

  function renderSyncSnapshot(container, snap) {
    var phase = snap.phase || "fetching";
    var total = snap.total_items || 0;
    var inspected = snap.inspected || 0;
    var provider = snap.provider || "";
    var pct = total > 0
      ? Math.min(100, Math.round((inspected / total) * 100))
      : 0;

    var bar = (phase === "fetching" || total === 0)
      ? '<div class="scan-progress-bar indeterminate">'
        + '<div class="scan-progress-fill"></div></div>'
      : '<div class="scan-progress-bar">'
        + '<div class="scan-progress-fill" style="width: '
        + pct + '%"></div></div>';

    var headline = phase === "fetching"
      ? "Preparing metadata sync..."
      : (total + " provider items to inspect");

    var counts = total > 0 || inspected > 0
      ? "<p>" + inspected + " / " + total + " inspected</p>"
        + "<p>" + syncCounterLine(snap) + "</p>"
      : "";

    var current = snap.current_item
      ? "<p>Now: " + snap.current_item.replace(/</g, "&lt;") + "</p>"
      : "";

    var timing = "";
    if (snap.elapsed != null) {
      timing = "<p>Elapsed " + syncFormatTime(snap.elapsed);
      if (snap.eta_seconds != null) {
        timing += " · estimated remaining "
          + syncFormatTime(snap.eta_seconds);
      } else if (phase === "syncing" && total > inspected) {
        timing += " · estimating remaining time...";
      }
      timing += "</p>";
    } else {
      timing = "<p>Calculating...</p>";
    }

    container.innerHTML =
      '<div class="scan-progress-head"><h3>' + provider
      + " metadata sync</h3></div>"
      + '<div class="scan-progress-status">' + headline + "</div>"
      + bar
      + '<div class="scan-progress-details">' + counts
      + current + timing + "</div>"
      + '<div class="scan-progress-humour" '
      + 'id="sync-humour"></div>';
  }

  function renderSyncResult(container, summary) {
    var ok = (summary.errors || []).length === 0;
    var cls = ok ? "scan-progress-complete" : "scan-progress-error";
    var title = ok
      ? "sync complete"
      : "sync finished with errors";
    var lines = [
      (summary.inspected || 0) + " items inspected",
      (summary.matched || 0) + " matched to NAMOA media",
      (summary.updated || 0) + " metadata records updated",
      (summary.unchanged || 0) + " unchanged",
      (summary.unmatched || 0) + " unmatched",
      (summary.needs_review || 0) + " need review",
      (summary.errors || []).length + " errors"
    ];
    var errText = ok
      ? ""
      : "<p>" + (summary.errors || []).slice(0, 3).join("; ")
        .replace(/</g, "&lt;") + "</p>";

    container.innerHTML =
      '<div class="scan-progress-head"><h3>' + summary.provider
      + " metadata " + title + "</h3></div>"
      + '<div class="scan-progress-status ' + cls + '">'
      + lines.join(" &middot; ") + "</div>" + errText
      + "<p>Reload the page for the stored summary.</p>";
  }

  function startSyncPolling(container) {
    var url = container.getAttribute("data-status-url");
    var humourIndex = 0;
    var humourTimer = null;

    var stopHumour = function () {
      if (humourTimer) {
        window.clearInterval(humourTimer);
        humourTimer = null;
      }
    };

    var poll = function () {
      fetch(url, { headers: { "Accept": "application/json" } })
        .then(function (response) { return response.json(); })
        .then(function (data) {
          var live = data.live || {};
          var names = data.providers || [];
          var pending = names.filter(function (name) {
            return !(data.results && data.results[name]);
          });

          if (!data.running && pending.length === 0) {
            var done = names.map(function (n) {
              return data.results[n] || (data.last_sync || {})[n];
            }).filter(function (s) { return !!s; });
            if (done.length > 0) {
              stopHumour();
              container.innerHTML = "";
              done.forEach(function (summary) {
                var block = document.createElement("div");
                container.appendChild(block);
                renderSyncResult(block, summary);
              });
            } else {
              container.innerHTML = "";
            }
            window.clearInterval(timer);
            return;
          }

          var first = pending.length > 0
            ? live[pending[0]]
            : live[names[0]];
          if (!first) { return; }

          renderSyncSnapshot(container, first);

          var humourEl = document.getElementById("sync-humour");
          if (humourEl && !humourTimer) {
            humourEl.textContent = SYNC_HUMOUR[0];
            humourTimer = window.setInterval(function () {
              humourIndex = (humourIndex + 1) % SYNC_HUMOUR.length;
              var el = document.getElementById("sync-humour");
              if (el) { el.textContent = SYNC_HUMOUR[humourIndex]; }
            }, 6000);
          }
        })
        .catch(function () {});
    };

    var timer = window.setInterval(poll, 2000);
    poll();
  }

  // Organisation shell: highlight the active workspace link in the
  // sidebar sub nav and the secondary bar. Server renders the same
  // hrefs; this only adds the active class for the current path.
  (function () {
    var path = window.location.pathname || "/";
    function orgKey(href) {
      if (path.indexOf("/organisation/profiles") === 0 && href === "/organisation/profiles") { return 2; }
      if (path === href) { return 2; }
      if (href !== "/" && href !== "/organisation" && path.indexOf(href + "/") === 0) { return 1; }
      return 0;
    }
    var best = "";
    var bestScore = 0;
    document.querySelectorAll("[data-orglink]").forEach(function (link) {
      var href = link.getAttribute("data-orglink") || "";
      var score = orgKey(href);
      if (score > bestScore) {
        bestScore = score;
        best = href;
      }
    });
    if (best) {
      document.querySelectorAll('[data-orglink="' + best + '"]').forEach(function (link) {
        link.classList.add("active");
        link.setAttribute("aria-current", "page");
      });
    }
  })();

  // Organisation profile setup progress and saving summary: live view
  // over the same in-memory form fields that the save path validates.
  // No second model: non-empty name, absolute source and destination
  // paths, at least one category with folder, movie and TV patterns
  // carrying a root tag, and a selected filename mode.
  function profileForm() {
    return document.getElementById("profile-edit-form");
  }

  function nonEmptyValues(selector) {
    var out = [];
    document.querySelectorAll(selector).forEach(function (field) {
      var value = (field.value || "").trim();
      if (value) { out.push(value); }
    });
    return out;
  }

  function syncProfileProgress() {
    var form = profileForm();
    if (!form) { return; }
    var progress = document.getElementById("profile-progress");
    var nameField = form.querySelector('input[name="name"]');
    var nameOk = !!(nameField && (nameField.value || "").trim());
    var sources = nonEmptyValues('#source-rows input[name="source"]');
    var sourcesOk = sources.some(function (v) { return v.charAt(0) === "/"; });
    var dests = nonEmptyValues('#root-rows input[name="root"]');
    var destsOk = dests.some(function (v) { return v.charAt(0) === "/"; });
    var catNames = nonEmptyValues('#cat-rows input[name="cat_name"]');
    var catFolders = nonEmptyValues('#cat-rows input[name="cat_folder"]');
    var catsOk = catNames.length > 0 && catFolders.length > 0;
    var movieField = form.querySelector('input[name="movie_template"]');
    var tvField = form.querySelector('input[name="tv_template"]');
    var movie = movieField ? (movieField.value || "") : "";
    var tv = tvField ? (tvField.value || "") : "";
    var foldersOk = !!movie.trim() && !!tv.trim() && movie.indexOf("{root") >= 0 && tv.indexOf("{root") >= 0;
    var modeChecked = form.querySelector('input[name="filename_mode"]:checked');
    var namingOk = !!modeChecked;
    var states = {
      name: nameOk,
      sources: sourcesOk,
      destinations: destsOk,
      categories: catsOk,
      folders: foldersOk,
      naming: namingOk
    };
    var done = 0;
    var total = 0;
    Object.keys(states).forEach(function (key) {
      total += 1;
      if (states[key]) { done += 1; }
    });
    if (progress) {
      progress.querySelectorAll("[data-progress-item]").forEach(function (item) {
        var key = item.getAttribute("data-progress-item");
        var ok = !!states[key];
        item.classList.toggle("done", ok);
        item.classList.toggle("todo", !ok);
        var mark = item.querySelector("span");
        if (mark) { mark.textContent = ok ? "✓" : "○"; }
      });
      var count = progress.querySelector("[data-progress-count]");
      if (count) { count.textContent = done + " of " + total + " complete"; }
    }
    function setText(selector, text) {
      var el = document.querySelector(selector);
      if (el) { el.textContent = text; }
    }
    setText("[data-summary-sources]", sources.length ? (sources.length + " configured") : "None configured yet");
    setText("[data-summary-dests]", dests.length ? (dests.length + " configured") : "None configured yet");
    var ruleCount = document.querySelectorAll('#rule-rows [data-repeat="rule"]').length;
    var catCount = document.querySelectorAll('#cat-rows [data-repeat="cat"]').length;
    setText("[data-summary-cats]", (catCount || catNames.length) ? (catCount + " categories, " + ruleCount + " rules") : "None configured yet");
    setText("[data-summary-folders]", (movie.trim() && tv.trim()) ? "Movie and TV configured" : "None configured yet");
    if (modeChecked) {
      var labels = { keep: "Keep existing filenames", clean: "Clean media names", extended: "Clean media names + extended naming", template: "Custom pattern" };
      setText("[data-summary-naming]", labels[modeChecked.value] || modeChecked.value);
    }
    var advCount = document.querySelectorAll('#cert-rows [data-repeat], #coll-rows [data-repeat], #map-rows [data-repeat], #sig-rows [data-repeat]').length;
    setText("[data-summary-advanced]", advCount ? (advCount + " advanced rows") : "Using default settings");
    setText("[data-count-sources]", sources.length ? ("(" + sources.length + " configured)") : "");
    setText("[data-count-dests]", dests.length ? ("(" + dests.length + " configured)") : "");
    setText("[data-count-cats]", catCount ? ("(" + catCount + " categories)") : "");
    setText("[data-count-rules]", ("(" + ruleCount + " rules)"));
  }

  document.addEventListener("input", function (event) {
    if (event.target && event.target.closest && event.target.closest("#profile-edit-form")) {
      syncProfileProgress();
    }
  });
  document.addEventListener("change", function (event) {
    if (event.target && event.target.closest && event.target.closest("#profile-edit-form")) {
      syncProfileProgress();
    }
  });
  document.addEventListener("click", function (event) {
    if (event.target && event.target.closest && event.target.closest("#source-add, #root-add, #cat-add, #rule-add, #cert-add, #coll-add, #map-add, #sig-add, .js-row-remove")) {
      window.setTimeout(syncProfileProgress, 0);
    }
  });

  syncProfileProgress();

  // Built-in defaults: copy the real built-in patterns into the live
  // Folder Structure inputs. No new route, no mock data.
  var builtinBtn = document.getElementById("builtin-apply");
  if (builtinBtn) {
    builtinBtn.addEventListener("click", function () {
      var form = profileForm();
      if (!form) { return; }
      var movie = builtinBtn.getAttribute("data-movie") || "";
      var tv = builtinBtn.getAttribute("data-tv") || "";
      var cat = builtinBtn.getAttribute("data-cat") || "";
      var movieField = form.querySelector('input[name="movie_template"]');
      var tvField = form.querySelector('input[name="tv_template"]');
      var catField = form.querySelector('input[name="category_template"]');
      if (movieField && movie) { movieField.value = movie; }
      if (tvField && tv) { tvField.value = tv; }
      if (catField && cat) { catField.value = cat; }
      syncProfileProgress();
      try { movieField.focus(); } catch (e) {}
    });
  }

  if (syncLive) {

    if (syncLive.getAttribute("data-running")) {
      startSyncPolling(syncLive);
    } else {
      fetch(
        syncLive.getAttribute("data-status-url"),
        { headers: { "Accept": "application/json" } }
      )
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (data && data.running) {
            startSyncPolling(syncLive);
          }
        })
        .catch(function () {});
    }
  }
})();
