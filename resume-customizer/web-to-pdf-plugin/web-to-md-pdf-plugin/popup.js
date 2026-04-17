// 简历优化助手 - Popup 脚本 (后台任务版 v2.2)
// 支持后台处理，关闭 popup 不会中断任务
// v2.2: 新增 AI 问答助手功能

console.log('Resume Optimizer Plugin v2.2 loaded');

const API_BASE = 'http://127.0.0.1:8000';
let currentTabId = null;
let pollingInterval = null;
let qaPollingInterval = null;
let currentResult = null;
let currentQAResult = null;

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', async () => {
  console.log('DOMContentLoaded - initializing popup');
  
  // 获取当前标签页
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentTabId = tab.id;
  
  console.log('Current tab ID:', currentTabId);
  
  // 绑定事件
  bindEvents();
  
  // 首先检查是否有已完成的任务（无论后端状态）
  const hasExistingTask = await checkExistingTask();
  
  // 检查是否有已完成的 QA 任务
  const hasExistingQATask = await checkExistingQATask();
  
  // 如果没有已存在的任务，再检查后端状态
  if (!hasExistingTask) {
    console.log('No existing task, checking backend status at:', API_BASE);
    await checkBackendStatus();
  }
});

// 绑定所有事件
function bindEvents() {
  document.getElementById('optimizeBtn').addEventListener('click', startOptimization);
  document.getElementById('downloadPdf').addEventListener('click', downloadPdf);
  document.getElementById('downloadWord').addEventListener('click', downloadWord);
  document.getElementById('historyBtn').addEventListener('click', showHistory);
  document.getElementById('qaBtn').addEventListener('click', startQA);
  
  // 事件委托：处理所有复制按钮点击
  document.getElementById('qaResults').addEventListener('click', async (e) => {
    if (e.target.classList.contains('copy-btn')) {
      const answerText = e.target.dataset.answer;
      await copyToClipboard(answerText, e.target);
    }
  });
}

// 检查是否有已存在的任务
async function checkExistingTask() {
  try {
    const response = await chrome.runtime.sendMessage({
      action: 'getTaskStatus',
      tabId: currentTabId,
      taskType: 'resume'  // 指定任务类型
    });
    
    console.log('checkExistingTask response:', response);
    
    if (response && response.status) {
      console.log('Found existing task:', response);
      
      if (response.status === 'processing') {
        // 任务正在处理中，开始轮询
        showProcessingState(response.message || '正在处理中...');
        startPolling();
        return true;
      } else if (response.status === 'completed') {
        // 任务已完成，显示结果
        currentResult = response.result;
        displayResults(response.result);
        showSuccessState(response.result);
        return true;
      } else if (response.status === 'error') {
        // 任务失败
        showErrorState(response.error);
        return true;
      }
    }
    return false;
  } catch (error) {
    console.error('Error checking existing task:', error);
    return false;
  }
}

// 检查是否有已存在的 QA 任务
async function checkExistingQATask() {
  try {
    const response = await chrome.runtime.sendMessage({
      action: 'getTaskStatus',
      tabId: currentTabId,
      taskType: 'qa'  // 指定 QA 任务类型
    });
    
    console.log('checkExistingQATask response:', response);
    
    if (response && response.status) {
      console.log('Found existing QA task:', response);
      
      if (response.status === 'processing') {
        // QA 任务正在处理中，开始轮询
        showQAProcessingState(response.message || '正在处理中...');
        startQAPolling();
        return true;
      } else if (response.status === 'completed') {
        // QA 任务已完成，显示结果
        currentQAResult = response.result;
        displayQAResults(response.result);
        showQASuccessState();
        return true;
      } else if (response.status === 'error') {
        // QA 任务失败
        showQAErrorState(response.error);
        return true;
      }
    }
    return false;
  } catch (error) {
    console.error('Error checking existing QA task:', error);
    return false;
  }
}

// 开始优化
async function startOptimization() {
  const btn = document.getElementById('optimizeBtn');
  const statusEl = document.getElementById('status');
  
  btn.disabled = true;
  showProcessingState('正在提取网页内容...');
  
  try {
    // 获取当前标签页
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const currentUrl = tab.url;
    
    // 注入 content.js 并获取页面内容
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js']
    });
    
    // 获取页面文本
    const response = await chrome.tabs.sendMessage(tab.id, { action: "getText" });
    
    if (!response || !response.text) {
      throw new Error('无法提取网页内容，请刷新页面重试');
    }
    
    console.log('Extracted text length:', response.text.length);
    
    showProcessingState('已提交到后台处理，可以切换到其他页面...');
    
    // 发送到后台处理
    await chrome.runtime.sendMessage({
      action: 'startOptimization',
      tabId: currentTabId,
      taskType: 'resume',  // 指定任务类型
      jobDescription: response.text,
      sourceUrl: currentUrl
    });
    
    // 开始轮询状态
    startPolling();
    
  } catch (error) {
    console.error('Error:', error);
    showErrorState(error.message);
    btn.disabled = false;
  }
}

// 开始轮询任务状态
function startPolling() {
  if (pollingInterval) {
    clearInterval(pollingInterval);
  }
  
  pollingInterval = setInterval(async () => {
    try {
      const response = await chrome.runtime.sendMessage({
        action: 'getTaskStatus',
        tabId: currentTabId,
        taskType: 'resume'  // 指定任务类型
      });
      
      if (!response) return;
      
      if (response.status === 'completed') {
        stopPolling();
        currentResult = response.result;
        displayResults(response.result);
        showSuccessState(response.result);
      } else if (response.status === 'error') {
        stopPolling();
        showErrorState(response.error);
      } else if (response.status === 'processing') {
        showProcessingState(response.message || '正在处理中...');
      }
    } catch (error) {
      console.error('Polling error:', error);
    }
  }, 1000); // 每秒检查一次
}

// 停止轮询
function stopPolling() {
  if (pollingInterval) {
    clearInterval(pollingInterval);
    pollingInterval = null;
  }
}

// 显示处理中状态
function showProcessingState(message) {
  const btn = document.getElementById('optimizeBtn');
  const statusEl = document.getElementById('status');
  
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>后台处理中...';
  
  statusEl.className = 'status loading';
  statusEl.innerHTML = `
    <div style="display: flex; align-items: center; gap: 8px;">
      <span class="spinner" style="border-color: #1967d2; border-top-color: transparent;"></span>
      <span>${message}</span>
    </div>
    <div style="margin-top: 8px; font-size: 11px; color: #5f6368;">
      💡 提示：你可以关闭此窗口切换到其他页面，任务会在后台继续处理
    </div>
  `;
  statusEl.style.display = 'block';
}

// 显示成功状态
function showSuccessState(result) {
  const btn = document.getElementById('optimizeBtn');
  const statusEl = document.getElementById('status');
  
  btn.disabled = true;
  btn.innerHTML = '✅ 优化完成';
  
  statusEl.className = 'status success';
  statusEl.innerHTML = `
    ✓ 优化成功！<br>
    公司: ${result.company_name}<br>
    岗位: ${result.job_title}
    <br><br>
    <button id="newTaskBtn" class="history-btn" style="margin: 0; font-size: 11px;">🔄 清除结果，开始新任务</button>
  `;
  statusEl.style.display = 'block';
  
  // 绑定新任务按钮
  document.getElementById('newTaskBtn').addEventListener('click', clearAndRestart);
}

// 显示错误状态
function showErrorState(errorMessage) {
  const btn = document.getElementById('optimizeBtn');
  const statusEl = document.getElementById('status');
  
  btn.disabled = false;
  btn.innerHTML = '✨ 提取职位描述并优化简历';
  
  statusEl.className = 'status error';
  statusEl.textContent = `✗ 错误: ${errorMessage}`;
  statusEl.style.display = 'block';
}

// 清除任务并重新开始
async function clearAndRestart() {
  await chrome.runtime.sendMessage({
    action: 'clearTask',
    tabId: currentTabId,
    taskType: 'resume'  // 指定任务类型
  });
  
  // 重置 UI
  const btn = document.getElementById('optimizeBtn');
  btn.disabled = false;
  btn.innerHTML = '✨ 提取职位描述并优化简历';
  
  document.getElementById('status').style.display = 'none';
  document.getElementById('resultPanel').style.display = 'none';
  document.getElementById('downloadBtns').style.display = 'none';
  document.getElementById('suggestions').style.display = 'none';
  
  currentResult = null;
}

// PDF 下载
function downloadPdf() {
  if (currentResult && currentResult.pdf_url) {
    const downloadUrl = `${API_BASE}${currentResult.pdf_url}`;
    chrome.downloads.download({
      url: downloadUrl,
      filename: currentResult.pdf_filename || 'resume.pdf',
      saveAs: true
    });
  }
}

// Word 下载
function downloadWord() {
  if (currentResult && currentResult.word_url) {
    const downloadUrl = `${API_BASE}${currentResult.word_url}`;
    chrome.downloads.download({
      url: downloadUrl,
      filename: currentResult.word_filename || 'resume.docx',
      saveAs: true
    });
  }
}

// 显示结果
function displayResults(result) {
  const panel = document.getElementById('resultPanel');
  const title = document.getElementById('resultTitle');
  const matchScore = document.getElementById('matchScore');
  const modCount = document.getElementById('modCount');
  const modificationsDiv = document.getElementById('modifications');
  
  // 设置标题
  title.textContent = `${result.company_name} - ${result.job_title}`;
  
  // 设置元数据
  matchScore.textContent = `匹配度: ${result.match_score}%`;
  modCount.textContent = `修改: ${result.success_count}/${result.total_count}`;
  
  // 清空之前的修改列表
  modificationsDiv.innerHTML = '';
  
  // 显示修改详情
  if (result.modifications && result.modifications.length > 0) {
    result.modifications.forEach(mod => {
      const item = document.createElement('div');
      item.className = `mod-item ${mod.success ? 'success' : 'failed'}`;
      
      const icon = mod.success ? '✅' : '❌';
      const target = truncate(mod.target, 30);
      const replacement = truncate(mod.replacement, 30);
      
      if (mod.success) {
        item.innerHTML = `
          <div>
            <span class="mod-icon">${icon}</span>
            <span class="mod-target">${escapeHtml(target)}</span>
            <span class="mod-arrow">→</span>
            <span class="mod-replacement">${escapeHtml(replacement)}</span>
          </div>
          <div class="mod-reason">${escapeHtml(mod.reason)}</div>
        `;
      } else {
        item.innerHTML = `
          <div>
            <span class="mod-icon">${icon}</span>
            <span class="mod-target">${escapeHtml(target)}</span>
          </div>
          <div class="mod-error">${escapeHtml(mod.error_message || '未找到匹配内容')}</div>
        `;
      }
      
      modificationsDiv.appendChild(item);
    });
  }
  
  // 显示建议
  if (result.suggestions && result.suggestions.length > 0) {
    const suggestionsDiv = document.getElementById('suggestions');
    const suggestionList = document.getElementById('suggestionList');
    suggestionList.innerHTML = '';
    
    result.suggestions.forEach(suggestion => {
      const li = document.createElement('li');
      li.textContent = suggestion;
      suggestionList.appendChild(li);
    });
    
    suggestionsDiv.style.display = 'block';
  }
  
  // 显示面板和下载按钮
  panel.style.display = 'block';
  document.getElementById('downloadBtns').style.display = 'flex';
}

// 历史记录
let historyVisible = false;

async function showHistory() {
  const panel = document.getElementById('historyPanel');
  
  // 切换显示/隐藏
  if (historyVisible) {
    panel.classList.remove('show');
    historyVisible = false;
    return;
  }
  
  try {
    const response = await fetch(`${API_BASE}/api/logs?limit=50`);
    if (response.ok) {
      const data = await response.json();
      renderHistoryPanel(data.logs);
      panel.classList.add('show');
      historyVisible = true;
    } else {
      alert('无法获取历史记录');
    }
  } catch (error) {
    console.error('Error fetching logs:', error);
    alert('获取历史记录失败: ' + error.message);
  }
}

// 渲染历史记录面板
function renderHistoryPanel(logs) {
  const panel = document.getElementById('historyPanel');
  
  if (logs.length === 0) {
    panel.innerHTML = '<div class="history-item"><div class="history-item-title">暂无历史记录</div></div>';
    return;
  }
  
  panel.innerHTML = logs.map((log, index) => {
    const date = new Date(log.timestamp).toLocaleString('zh-CN');
    const hasFiles = log.pdf_filename || log.word_filename;
    
    return `
      <div class="history-item">
        <div class="history-item-header">
          <span class="history-item-title">${escapeHtml(log.company_name)} - ${escapeHtml(log.job_title)}</span>
          <span class="history-item-date">${date}</span>
        </div>
        <div class="history-item-meta">
          匹配度: ${log.match_score}% | 成功: ${log.success_count}/${log.total_count}
        </div>
        ${hasFiles ? `
          <div class="history-item-btns">
            ${log.pdf_filename ? `<button class="history-download-btn pdf" data-task-id="${log.task_id}" data-filename="${log.pdf_filename}">📄 PDF</button>` : ''}
            ${log.word_filename ? `<button class="history-download-btn word" data-task-id="${log.task_id}" data-filename="${log.word_filename}">📝 Word</button>` : ''}
          </div>
        ` : '<div class="history-item-meta" style="color: #ea4335;">文件已过期</div>'}
      </div>
    `;
  }).join('');
  
  // 重新绑定下载按钮事件监听器
  panel.querySelectorAll('.history-download-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      const taskId = this.dataset.taskId;
      const filename = this.dataset.filename;
      downloadHistoryFile(taskId, filename);
    });
  });
}

// 下载历史记录中的文件
function downloadHistoryFile(taskId, filename) {
  console.log('下载文件:', taskId, filename);
  const downloadUrl = `${API_BASE}/api/download/${taskId}/${filename}`;
  
  chrome.downloads.download({
    url: downloadUrl,
    filename: filename,
    saveAs: true
  }, (downloadId) => {
    if (chrome.runtime.lastError) {
      console.error('下载失败:', chrome.runtime.lastError);
      alert(`下载失败: ${chrome.runtime.lastError.message}`);
    } else {
      console.log('下载开始, ID:', downloadId);
    }
  });
}

// 显示结果
function displayResults(result) {
  const panel = document.getElementById('resultPanel');
  const title = document.getElementById('resultTitle');
  const matchScore = document.getElementById('matchScore');
  const modCount = document.getElementById('modCount');
  const modificationsDiv = document.getElementById('modifications');
  
  // 设置标题
  title.textContent = `${result.company_name} - ${result.job_title}`;
  
  // 设置元数据
  matchScore.textContent = `匹配度: ${result.match_score}%`;
  modCount.textContent = `修改: ${result.success_count}/${result.total_count}`;
  
  // 清空之前的修改列表
  modificationsDiv.innerHTML = '';
  
  // 显示修改详情
  if (result.modifications && result.modifications.length > 0) {
    result.modifications.forEach(mod => {
      const item = document.createElement('div');
      item.className = `mod-item ${mod.success ? 'success' : 'failed'}`;
      
      const icon = mod.success ? '✅' : '❌';
      const target = truncate(mod.target, 30);
      const replacement = truncate(mod.replacement, 30);
      
      if (mod.success) {
        item.innerHTML = `
          <div>
            <span class="mod-icon">${icon}</span>
            <span class="mod-target">${escapeHtml(target)}</span>
            <span class="mod-arrow">→</span>
            <span class="mod-replacement">${escapeHtml(replacement)}</span>
          </div>
          <div class="mod-reason">${escapeHtml(mod.reason)}</div>
        `;
      } else {
        item.innerHTML = `
          <div>
            <span class="mod-icon">${icon}</span>
            <span class="mod-target">${escapeHtml(target)}</span>
          </div>
          <div class="mod-error">${escapeHtml(mod.error_message || '未找到匹配内容')}</div>
        `;
      }
      
      modificationsDiv.appendChild(item);
    });
  }
  
  // 显示建议
  if (result.suggestions && result.suggestions.length > 0) {
    const suggestionsDiv = document.getElementById('suggestions');
    const suggestionList = document.getElementById('suggestionList');
    suggestionList.innerHTML = '';
    
    result.suggestions.forEach(suggestion => {
      const li = document.createElement('li');
      li.textContent = suggestion;
      suggestionList.appendChild(li);
    });
    
    suggestionsDiv.style.display = 'block';
  }
  
  // 显示面板和下载按钮
  panel.style.display = 'block';
  document.getElementById('downloadBtns').style.display = 'flex';
}

// 辅助函数：截断文本
function truncate(text, maxLen) {
  if (!text) return '';
  return text.length > maxLen ? text.substring(0, maxLen) + '...' : text;
}

// 辅助函数：转义 HTML
function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// 检查后端状态
async function checkBackendStatus() {
  const statusEl = document.getElementById('status');
  
  try {
    // 使用简单的 fetch 请求，不使用 AbortSignal.timeout（可能有兼容性问题）
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 3000);
    
    const response = await fetch(`${API_BASE}/api/health`, { 
      method: 'GET',
      mode: 'cors',
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    if (response.ok) {
      console.log('Backend is running');
      return true;
    } else {
      console.warn('Backend returned non-OK status:', response.status);
      statusEl.className = 'status error';
      statusEl.textContent = `⚠️ 后端服务响应异常 (HTTP ${response.status})`;
      statusEl.style.display = 'block';
      return false;
    }
  } catch (error) {
    console.warn('Backend check failed:', error.name, error.message);
    statusEl.className = 'status error';
    
    if (error.name === 'AbortError') {
      statusEl.textContent = '⚠️ 后端服务响应超时，请检查服务器是否运行在 127.0.0.1:8000';
    } else if (error.name === 'TypeError' && error.message.includes('Failed to fetch')) {
      statusEl.textContent = '⚠️ 无法连接后端服务，请确保 Python 服务器正在运行';
    } else {
      statusEl.textContent = `⚠️ 后端检查失败: ${error.message}`;
    }
    statusEl.style.display = 'block';
    return false;
  }
}

// 页面卸载时停止轮询
window.addEventListener('beforeunload', () => {
  stopPolling();
  stopQAPolling();
});

// ========== AI 问答助手功能 ==========

// 开始 QA 任务
async function startQA() {
  const btn = document.getElementById('qaBtn');
  const statusEl = document.getElementById('qaStatus');
  
  btn.disabled = true;
  showQAProcessingState('正在提取网页内容...');
  
  try {
    // 获取当前标签页
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const currentUrl = tab.url;
    
    // 注入 content.js 并获取页面内容
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files: ['content.js']
    });
    
    // 获取页面文本
    const response = await chrome.tabs.sendMessage(tab.id, { action: "getText" });
    
    if (!response || !response.text) {
      throw new Error('无法提取网页内容，请刷新页面重试');
    }
    
    console.log('QA: Extracted text length:', response.text.length);
    
    showQAProcessingState('已提交到后台处理，可以切换到其他页面...');
    
    // 发送到后台处理
    await chrome.runtime.sendMessage({
      action: 'startAnswerQuestions',
      tabId: currentTabId,
      taskType: 'qa',
      pageText: response.text,
      sourceUrl: currentUrl
    });
    
    // 开始轮询状态
    startQAPolling();
    
  } catch (error) {
    console.error('QA Error:', error);
    showQAErrorState(error.message);
    btn.disabled = false;
  }
}

// 开始轮询 QA 任务状态
function startQAPolling() {
  if (qaPollingInterval) {
    clearInterval(qaPollingInterval);
  }
  
  qaPollingInterval = setInterval(async () => {
    try {
      const response = await chrome.runtime.sendMessage({
        action: 'getTaskStatus',
        tabId: currentTabId,
        taskType: 'qa'
      });
      
      if (!response) return;
      
      if (response.status === 'completed') {
        stopQAPolling();
        currentQAResult = response.result;
        displayQAResults(response.result);
        showQASuccessState();
      } else if (response.status === 'error') {
        stopQAPolling();
        showQAErrorState(response.error);
      } else if (response.status === 'processing') {
        showQAProcessingState(response.message || '正在处理中...');
      }
    } catch (error) {
      console.error('QA Polling error:', error);
    }
  }, 1000);
}

// 停止 QA 轮询
function stopQAPolling() {
  if (qaPollingInterval) {
    clearInterval(qaPollingInterval);
    qaPollingInterval = null;
  }
}

// 显示 QA 处理中状态
function showQAProcessingState(message) {
  const btn = document.getElementById('qaBtn');
  const statusEl = document.getElementById('qaStatus');
  
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>后台处理中...';
  
  statusEl.className = 'qa-status loading';
  statusEl.innerHTML = `
    <div style="display: flex; align-items: center; gap: 8px;">
      <span class="spinner" style="border-color: #7c3aed; border-top-color: transparent;"></span>
      <span>${message}</span>
    </div>
    <div style="margin-top: 8px; font-size: 11px; color: #5f6368;">
      💡 提示：你可以关闭此窗口切换到其他页面，任务会在后台继续处理
    </div>
  `;
  statusEl.style.display = 'block';
}

// 显示 QA 成功状态
function showQASuccessState() {
  const btn = document.getElementById('qaBtn');
  const statusEl = document.getElementById('qaStatus');
  
  btn.disabled = true;
  btn.innerHTML = '✅ 答案生成完成';
  
  statusEl.className = 'qa-status success';
  statusEl.innerHTML = `
    ✓ 问答生成成功！点击答案旁的复制按钮即可复制。<br>
    <button id="newQATaskBtn" class="history-btn" style="margin: 8px 0 0 0; font-size: 11px;">🔄 清除结果，重新生成</button>
  `;
  statusEl.style.display = 'block';
  
  // 绑定新任务按钮
  document.getElementById('newQATaskBtn').addEventListener('click', clearAndRestartQA);
}

// 显示 QA 错误状态
function showQAErrorState(errorMessage) {
  const btn = document.getElementById('qaBtn');
  const statusEl = document.getElementById('qaStatus');
  
  btn.disabled = false;
  btn.innerHTML = '🔍 提取问题并生成答案';
  
  statusEl.className = 'qa-status error';
  statusEl.textContent = `✗ 错误: ${errorMessage}`;
  statusEl.style.display = 'block';
}

// 清除 QA 任务并重新开始
async function clearAndRestartQA() {
  await chrome.runtime.sendMessage({
    action: 'clearTask',
    tabId: currentTabId,
    taskType: 'qa'
  });
  
  // 重置 UI
  const btn = document.getElementById('qaBtn');
  btn.disabled = false;
  btn.innerHTML = '🔍 提取问题并生成答案';
  
  document.getElementById('qaStatus').style.display = 'none';
  document.getElementById('qaResults').classList.remove('show');
  document.getElementById('qaResults').innerHTML = '';
  
  currentQAResult = null;
}

// 显示 QA 结果
function displayQAResults(result) {
  const container = document.getElementById('qaResults');
  container.innerHTML = '';
  
  if (!result || !result.questions || result.questions.length === 0) {
    container.innerHTML = '<div class="qa-item"><div class="qa-question">未找到需要回答的问题</div></div>';
    container.classList.add('show');
    return;
  }
  
  result.questions.forEach((qa, index) => {
    const item = document.createElement('div');
    item.className = 'qa-item';
    item.innerHTML = `
      <div class="qa-question">Q${index + 1}: ${escapeHtml(qa.question)}</div>
      <div class="qa-answer">${escapeHtml(qa.answer)}</div>
      <div class="qa-copy-row">
        <button class="copy-btn" data-answer="${escapeHtml(qa.answer).replace(/"/g, '&quot;')}">📋 复制答案</button>
      </div>
    `;
    container.appendChild(item);
  });
  
  container.classList.add('show');
}

// 复制到剪贴板
async function copyToClipboard(text, button) {
  try {
    await navigator.clipboard.writeText(text);
    const originalText = button.textContent;
    button.textContent = '✓ 已复制';
    button.classList.add('copied');
    setTimeout(() => {
      button.textContent = originalText;
      button.classList.remove('copied');
    }, 2000);
  } catch (err) {
    console.error('Copy failed:', err);
    // 降级方案：使用 textarea
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);
    textarea.select();
    document.execCommand('copy');
    document.body.removeChild(textarea);
    
    button.textContent = '✓ 已复制';
    button.classList.add('copied');
    setTimeout(() => {
      button.textContent = '📋 复制答案';
      button.classList.remove('copied');
    }, 2000);
  }
}
