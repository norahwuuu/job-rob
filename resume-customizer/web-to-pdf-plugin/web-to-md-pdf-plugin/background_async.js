// 后端 API 地址
const API_BASE = 'http://localhost:8000';

// Service Worker 启动时
console.log('[Background] Service worker started');

// 处理来自 popup 的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'optimizeResume') {
    console.log(`[Background] Received optimization request from tab ${request.tabId}`);
    handleOptimization(request.job_description, request.source_url, request.tabId);
    sendResponse({status: 'started'});
  } else if (request.action === 'getTaskStatus') {
    getTaskStatus(request.tabId).then(sendResponse);
    return true; // 异步响应
  } else if (request.action === 'clearTask') {
    clearTask(request.tabId).then(sendResponse);
    return true;
  }
});

// 处理优化请求
async function handleOptimization(jobDescription, sourceUrl, tabId) {
  // 初始化状态
  await updateTaskStatus(tabId, {
    status: 'processing',
    message: '正在提交任务...',
    timestamp: Date.now()
  });
  
  try {
    // 步骤1: 提交任务到后端
    const formData = new FormData();
    formData.append('job_description', jobDescription);
    formData.append('source_url', sourceUrl);
    formData.append('skip_pdf', 'false');
    
    console.log(`[Background] Submitting task to API...`);
    
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 10000); // 10秒超时
    
    const response = await fetch(`${API_BASE}/api/modify-resume`, {
      method: 'POST',
      body: formData,
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `HTTP ${response.status}`);
    }
    
    const taskData = await response.json();
    const taskId = taskData.task_id;
    console.log(`[Background] Task ${taskId} submitted, polling for result...`);
    
    // 步骤2: 轮询任务状态
    let attempts = 0;
    const maxAttempts = 300; // 最多300次，每次2秒 = 10分钟
    
    while (attempts < maxAttempts) {
      attempts++;
      
      // 等待2秒
      await new Promise(resolve => setTimeout(resolve, 2000));
      
      // 查询任务状态
      const statusResponse = await fetch(`${API_BASE}/api/task-status/${taskId}`);
      
      if (!statusResponse.ok) {
        throw new Error(`无法查询任务状态: HTTP ${statusResponse.status}`);
      }
      
      const statusData = await statusResponse.json();
      console.log(`[Background] Task ${taskId} status: ${statusData.status} (${attempts}/${maxAttempts})`);
      
      // 更新进度
      await updateTaskStatus(tabId, {
        status: 'processing',
        message: statusData.progress || '正在处理...',
        timestamp: Date.now()
      });
      
      if (statusData.status === 'completed') {
        // 任务完成
        const result = statusData.result;
        
        if (!result || !result.success) {
          throw new Error(result?.error || '优化失败');
        }
        
        // 更新状态为完成
        await updateTaskStatus(tabId, {
          status: 'completed',
          result: result,
          timestamp: Date.now()
        });
        
        // 发送通知
        try {
          chrome.notifications.create({
            type: 'basic',
            iconUrl: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAA7AAAAOwBeShxvQAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAAGkSUIBVFiFzdW/L0RBEMDxz104iR+Fw3FFKF0h0fgRiVqjodD4KzQKEo1GI9GIQkMoNEpKhYZIJBqNxh+w390ru/u+u+y+e0Qx2bzc7Ozszuzb3Q1KKQX/LwI/a2Z2AldLBNbiHnZiKxZiWq4GcBtXcBEPugiYyTH8wG4cxCpMxjxcx3L0FgHvMQ17s2Z2E1NYlUe/jxHYhzuYneGDWI+D+IDVGIPPWIb+vAHVqBEAT7C0wuNVrMUjzOtAsKS+5YMu5JrgQ7gGt9swM8cS/A5OYQhmYnuG1+IBVmAprmFjxr8CdyIh/MATDEE/3sWiHJdWlPIEfNe8xOhMwEa8xSoMZJxBv/p0EvdxHV2IeDDGohTnMSETQzAfB3C4yoZnOIsxqjz6FvxEewJexGZMxaT8/xGO4jYuqPLpdwJIoqn4jIXqO24rLmXG71qTy4QPy7CmQ9xXbML0EkcJk3ABbXR6rgv4gTmYl8nQP+nDIyzG4xyL6v/qE+hGEwewIQupB0tG3cIR9GfceozAdNxpd+u4jmfYkmOlvMRwfMEDdLQx/gD6RP4AAAAASUVORK5CYII=',
            title: '简历优化完成',
            message: `${result.company_name} - ${result.job_title} | 匹配度: ${result.match_score}%`
          });
        } catch (e) {
          console.warn('[Background] Notification failed:', e);
        }
        
        console.log(`[Background] Optimization completed for tab ${tabId}`);
        return; // 成功完成
        
      } else if (statusData.status === 'error') {
        // 任务失败
        throw new Error(statusData.error || '处理失败');
      }
      
      // 继续轮询...
    }
    
    // 超过最大尝试次数
    throw new Error('任务处理超时（超过10分钟）');
    
  } catch (error) {
    console.error(`[Background] Error for tab ${tabId}:`, error);
    
    // 处理超时错误
    let errorMessage = error.message;
    if (error.name === 'AbortError') {
      errorMessage = '请求超时，请检查后端服务是否运行正常';
    }
    
    // 更新状态为错误
    await updateTaskStatus(tabId, {
      status: 'error',
      error: errorMessage,
      timestamp: Date.now()
    });
    
    // 发送错误通知
    try {
      chrome.notifications.create({
        type: 'basic',
        iconUrl: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAA7AAAAOwBeShxvQAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAAGkSURBVFiFzdW/L0RBEMDxz104iR+Fw3FFKF0h0fgRiVqjodD4KzQKEo1GI9GIQkMoNEpKhYZIJBqNxh+w390ru/u+u+y+e0Qx2bzc7Ozszuzb3Q1KKQX/LwI/a2Z2AldLBNbiHnZiKxZiWq4GcBtXcBEPugiYyTH8wG4cxCpMxjxcx3L0FgHvMQ17s2Z2E1NYlUe/jxHYhzuYneGDWI+D+IDVGIPPWIb+vAHVqBEAT7C0wuNVrMUjzOtAsKS+5YMu5JrgQ7gGt9swM8cS/A5OYQhmYnuG1+IBVmAprmFjxr8CdyIh/MATDEE/3sWiHJdWlPIEfNe8xOhMwEa8xSoMZJxBv/p0EvdxHV2IeDDGohTnMSETQzAfB3C4yoZnOIsxqjz6FvxEewJexGZMxaT8/xGO4jYuqPLpdwJIoqn4jIXqO24rLmXG71qTy4QPy7CmQ9xXbML0EkcJk3ABbXR6rgv4gTmYl8nQP+nDIyzG4xyL6v/qE+hGEwewIQupB0tG3cIR9GfceozAdNxpd+u4jmfYkmOlvMRwfMEDdLQx/gD6RP4AAAAASUVORK5CYII=',
        title: '简历优化失败',
        message: errorMessage
      });
    } catch (e) {
      console.warn('[Background] Notification failed:', e);
    }
  }
}

// 更新任务状态到 storage
async function updateTaskStatus(tabId, data) {
  const key = `task_${tabId}`;
  await chrome.storage.local.set({[key]: data});
  console.log(`[Background] Updated status for tab ${tabId}:`, data.status);
}

// 获取任务状态
async function getTaskStatus(tabId) {
  const key = `task_${tabId}`;
  const result = await chrome.storage.local.get(key);
  return result[key] || null;
}

// 清除任务
async function clearTask(tabId) {
  const key = `task_${tabId}`;
  await chrome.storage.local.remove(key);
  console.log(`[Background] Cleared task for tab ${tabId}`);
  return {status: 'cleared'};
}

// 定期清理旧任务（超过24小时）
async function cleanupOldTasks() {
  const items = await chrome.storage.local.get(null);
  const now = Date.now();
  const maxAge = 24 * 60 * 60 * 1000; // 24小时
  
  for (const [key, value] of Object.entries(items)) {
    if (key.startsWith('task_') && value.timestamp) {
      if (now - value.timestamp > maxAge) {
        await chrome.storage.local.remove(key);
        console.log(`[Background] Cleaned up old task: ${key}`);
      }
    }
  }
}

// 每小时清理一次
setInterval(cleanupOldTasks, 60 * 60 * 1000);
