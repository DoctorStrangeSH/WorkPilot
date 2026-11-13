/* Deterministic matching for already-open, user-mapped resource tabs.
 * This module performs no browser calls and never infers a resource from page text.
 */
var MaleniaTabDiscovery = (() => {
  const ROLES = ["inventory", "datalens", "asgard"];

  function normalizeMapping(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
      throw new Error("invalid_mappings");
    }
    const result = {};
    for (const role of ROLES) {
      const entry = raw[role];
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
        throw new Error("missing_mapping");
      }
      let url;
      try { url = new URL(entry.origin); } catch { throw new Error("invalid_origin"); }
      if (url.protocol !== "https:" || url.username || url.password ||
          url.pathname !== "/" || url.search || url.hash || url.port) {
        throw new Error("unsafe_origin");
      }
      const pathPrefix = entry.pathPrefix === undefined ? "/" : entry.pathPrefix;
      if (typeof pathPrefix !== "string" || !pathPrefix.startsWith("/") ||
          pathPrefix.startsWith("//") || pathPrefix.includes("?") ||
          pathPrefix.includes("#") || pathPrefix.includes("\\") ||
          pathPrefix.split("/").includes("..")) {
        throw new Error("invalid_path_prefix");
      }
      result[role] = {origin: url.origin, pathPrefix};
    }
    if (Object.keys(raw).some(key => !ROLES.includes(key))) {
      throw new Error("unknown_mapping_role");
    }
    return result;
  }

  function sanitizeTab(tab) {
    if (!tab || !Number.isSafeInteger(tab.id) || tab.id < 0 ||
        typeof tab.url !== "string" || tab.url.length > 4096) return null;
    let url;
    try { url = new URL(tab.url); } catch { return null; }
    if (url.protocol !== "https:" || !url.hostname || url.username ||
        url.password || url.port) return null;
    const title = typeof tab.title === "string"
      ? tab.title.replace(/[\\u0000-\\u001f\\u007f]/g, " ").slice(0, 200)
      : "";
    return {
      tabId: tab.id,
      windowId: Number.isSafeInteger(tab.windowId) ? tab.windowId : null,
      active: tab.active === true,
      title,
      origin: url.origin,
      path: url.pathname || "/",
      sanitizedUrl: url.origin + (url.pathname || "/")
    };
  }

  function hasPermission(patterns, origin) {
    return patterns.some(pattern => pattern === origin + "/*");
  }

  function matchesPath(path, prefix) {
    if (prefix === "/") return true;
    const normalized = prefix.endsWith("/") ? prefix.slice(0, -1) : prefix;
    return path === normalized || path.startsWith(normalized + "/");
  }

  function discover(tabs, rawMappings, grantedOriginPatterns) {
    if (!Array.isArray(tabs) || !Array.isArray(grantedOriginPatterns)) {
      throw new Error("invalid_discovery_input");
    }
    const mappings = normalizeMapping(rawMappings);
    const candidates = {};
    for (const role of ROLES) {
      const mapping = mappings[role];
      candidates[role] = tabs.map(sanitizeTab).filter(tab =>
        tab && tab.origin === mapping.origin &&
        matchesPath(tab.path, mapping.pathPrefix) &&
        hasPermission(grantedOriginPatterns, mapping.origin)
      ).map(tab => ({
        role,
        tabId: tab.tabId,
        windowId: tab.windowId,
        active: tab.active,
        title: tab.title,
        origin: tab.origin,
        path: tab.path,
        sanitizedUrl: tab.sanitizedUrl
      })).sort((a, b) => Number(b.active) - Number(a.active) || a.tabId - b.tabId);
    }
    return {
      roles: Object.fromEntries(ROLES.map(role => [role, {
        candidates: candidates[role],
        state: candidates[role].length === 0 ? "not_found" :
          candidates[role].length === 1 ? "unique" : "ambiguous"
      }]))
    };
  }

  return Object.freeze({discover, normalizeMapping});
})();

if (typeof module !== "undefined" && module.exports) module.exports = MaleniaTabDiscovery;
