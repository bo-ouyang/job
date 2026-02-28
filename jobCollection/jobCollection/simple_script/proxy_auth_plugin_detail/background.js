var config = {
    mode: "fixed_servers",
    rules: { singleProxy: { scheme: "http", host: "103.236.77.95", port: parseInt(19166) }, bypassList: ["localhost"] }
};
chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});
function callbackFn(details) {
    return { authCredentials: { username: "d2006816196", password: "xc1zag9a" } };
}
chrome.webRequest.onAuthRequired.addListener(callbackFn, {urls: ["<all_urls>"]}, ["blocking"]);
