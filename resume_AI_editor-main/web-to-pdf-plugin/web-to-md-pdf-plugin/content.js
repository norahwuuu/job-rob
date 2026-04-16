// 监听来自 popup.js 的消息
chrome.runtime.onMessage.addListener(
    function(request, sender, sendResponse) {
      if (request.action === "getText") {
        // 获取整个页面的可见文本
        const pageText = document.body.innerText;
        // 将获取到的文本和页面标题一起作为响应发送回去
        sendResponse({ text: pageText, title: document.title });
      }
    }
  );