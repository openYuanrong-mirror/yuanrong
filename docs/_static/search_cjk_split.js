/**
 * search_cjk_split.js — CJK search query segmentation for Sphinx
 *
 * Overrides Sphinx's default splitQuery to segment continuous CJK text
 * using maximum forward matching against a dictionary of jieba-indexed
 * terms (generated at build time as search_cjk_dict.js).
 *
 * Example: "分布式计算引擎" → ["分布式", "计算", "引擎"]
 * Each segmented word matches jieba-indexed terms exactly (score 5),
 * instead of being treated as one giant token that fails to match.
 *
 * This script must load AFTER searchtools.js (which defines splitQuery)
 * and AFTER search_cjk_dict.js (which defines SEARCH_CJK_DICT).
 * Both are guaranteed by html_js_files ordering in conf.py.
 * Immediate execution ensures the override is in place before any search
 * is performed — Sphinx's Search.init() only sets up UI handlers and
 * does not call splitQuery until the user submits a search query.
 */

(function () {
  "use strict";

  if (typeof splitQuery === "undefined") {
    console.warn("search_cjk_split: splitQuery not found, CJK segmentation disabled");
    return;
  }
  if (typeof SEARCH_CJK_DICT === "undefined") {
    console.warn("search_cjk_split: SEARCH_CJK_DICT not loaded, CJK segmentation disabled");
    return;
  }

  var originalSplitQuery = splitQuery;

  var CJK_CHAR = /[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]/;
  var dictSet = new Set(SEARCH_CJK_DICT);
  var maxLen = 0;
  for (var i = 0; i < SEARCH_CJK_DICT.length; i++) {
    if (SEARCH_CJK_DICT[i].length > maxLen) maxLen = SEARCH_CJK_DICT[i].length;
  }

  splitQuery = function (query) {
    var tokens = originalSplitQuery(query);
    var result = [];
    for (var i = 0; i < tokens.length; i++) {
      var token = tokens[i];
      if (!token) continue;
      // Only segment the CJK portions within a mixed token,
      // preserving non-CJK characters (API, punctuation, etc.) intact.
      var parts = extractCJKParts(token);
      for (var j = 0; j < parts.length; j++) {
        if (CJK_CHAR.test(parts[j])) {
          result.push.apply(result, segmentCJK(parts[j]));
        } else {
          result.push(parts[j]);
        }
      }
    }
    return result;
  };

  // Split a token into alternating CJK and non-CJK segments.
  // "中文API文档" → ["中文", "API", "文档"]
  function extractCJKParts(token) {
    var parts = [];
    var current = "";
    var isCJK = CJK_CHAR.test(token.charAt(0));
    for (var i = 0; i < token.length; i++) {
      var ch = token.charAt(i);
      var chIsCJK = CJK_CHAR.test(ch);
      if (chIsCJK !== isCJK) {
        if (current) parts.push(current);
        current = ch;
        isCJK = chIsCJK;
      } else {
        current += ch;
      }
    }
    if (current) parts.push(current);
    return parts;
  }

  function segmentCJK(text) {
    var chars = Array.from(text);
    var segments = [];
    var pos = 0;
    while (pos < chars.length) {
      var matched = false;
      for (var len = Math.min(maxLen, chars.length - pos); len >= 2; len--) {
        var word = chars.slice(pos, pos + len).join("");
        if (dictSet.has(word)) {
          segments.push(word);
          pos += len;
          matched = true;
          break;
        }
      }
      if (!matched) {
        segments.push(chars[pos]);
        pos++;
      }
    }
    return segments;
  }
})();
