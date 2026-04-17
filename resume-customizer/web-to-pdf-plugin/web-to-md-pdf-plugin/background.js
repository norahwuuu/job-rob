// 简历优化助手 - 后台 Service Worker
// 负责处理 API 调用，即使 popup 关闭也能继续运行
// v2.2: 支持 resume 和 qa 两种任务类型

const API_BASE = 'http://127.0.0.1:8000';

// 存储每个标签页的任务状态
// 格式: { tabId_taskType: { status, result, error, timestamp } }
// taskType: 'resume' 或 'qa'

// 监听来自 popup 的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'startOptimization') {
    handleOptimization(request.tabId, request.jobDescription, request.sourceUrl, request.taskType || 'resume');
    sendResponse({ started: true });
  } else if (request.action === 'startAnswerQuestions') {
    handleAnswerQuestions(request.tabId, request.pageText, request.sourceUrl);
    sendResponse({ started: true });
  } else if (request.action === 'getTaskStatus') {
    const taskType = request.taskType || 'resume';
    getTaskStatus(request.tabId, taskType).then(sendResponse);
    return true; // 保持消息通道开放
  } else if (request.action === 'clearTask') {
    const taskType = request.taskType || 'resume';
    clearTask(request.tabId, taskType);
    sendResponse({ cleared: true });
  }
  return true;
});

// 处理优化任务
async function handleOptimization(tabId, jobDescription, sourceUrl, taskType = 'resume') {
  console.log(`[Background] Starting optimization for tab ${tabId}`);
  
  // 更新状态为处理中
  await updateTaskStatus(tabId, taskType, {
    status: 'processing',
    message: '正在提交任务到后端...',
    timestamp: Date.now()
  });
  
  try {
    // 调用后端 API
    const formData = new FormData();
    formData.append('job_description', jobDescription);
    formData.append('source_url', sourceUrl);
    formData.append('skip_pdf', 'false');
    
    // 使用 AbortController 设置超时（30秒提交超时）
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    
    console.log(`[Background] Sending request to API...`);
    
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
    
    console.log(`[Background] Received response, parsing JSON...`);
    const taskResponse = await response.json();
    
    // API 返回任务状态 (status: 'pending', task_id: 'xxx')
    const backendTaskId = taskResponse.task_id;
    console.log(`[Background] Task submitted: ${backendTaskId}`);
    
    // 更新状态
    await updateTaskStatus(tabId, taskType, {
      status: 'processing',
      message: '后端正在处理中...',
      backendTaskId: backendTaskId,
      timestamp: Date.now()
    });
    
    // 开始轮询后端任务状态
    await pollTaskStatus(tabId, backendTaskId, taskType);
    
  } catch (error) {
    console.error(`[Background] Error for tab ${tabId}:`, error);
    
    // 处理超时错误
    let errorMessage = error.message;
    if (error.name === 'AbortError') {
      errorMessage = '请求超时（超过30秒），请检查后端服务是否运行正常';
    }
    
    // 更新状态为错误
    await updateTaskStatus(tabId, taskType, {
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
      console.warn('Notification failed:', e);
    }
  }
}

// 轮询后端任务状态
async function pollTaskStatus(tabId, backendTaskId, taskType = 'resume') {
  const maxPolls = 180; // 最多轮询180次 (3分钟)
  const pollInterval = 1000; // 每秒轮询一次
  
  for (let i = 0; i < maxPolls; i++) {
    try {
      const response = await fetch(`${API_BASE}/api/task-status/${backendTaskId}`);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      
      const status = await response.json();
      console.log(`[Background] Poll ${i+1}: status=${status.status}`);
      
      if (status.status === 'completed') {
        // 任务完成
        const result = status.result;
        
        await updateTaskStatus(tabId, taskType, {
          status: 'completed',
          result: result,
          timestamp: Date.now()
        });
        
        // 发送通知
        try {
          const notifTitle = taskType === 'qa' ? 'AI 问答完成' : '简历优化完成';
          const notifMessage = taskType === 'qa' 
            ? `已生成 ${result.questions?.length || 0} 个问题的答案`
            : `${result.company_name} - ${result.job_title} | 匹配度: ${result.match_score}%`;
          
          chrome.notifications.create({
            type: 'basic',
            iconUrl: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAA7AAAAOwBeShxvQAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAAGkSURBVFiFzdW/L0RBEMDxz104iR+Fw3FFKF0h0fgRiVqjodD4KzQKEo1GI9GIQkMoNEpKhYZIJBqNxh+w390ru/u+u+y+e0Qx2bzc7Ozszuzb3Q1KKQX/LwI/a2Z2AldLBNbiHnZiKxZiWq4GcBtXcBEPugiYyTH8wG4cxCpMxjxcx3L0FgHvMQ17s2Z2E1NYlUe/jxHYhzuYneGDWI+D+IDVGIPPWIb+vAHVqBEAT7C0wuNVrMUjzOtAsKS+5YMu5JrgQ7gGt9swM8cS/A5OYQhmYnuG1+IBVmAprmFjxr8CdyIh/MATDEE/3sWiHJdWlPIEfNe8xOhMwEa8xSoMZJxBv/p0EvdxHV2IeDDGohTnMSETQzAfB3C4yoZnOIsxqjz6FvxEewJexGZMxaT8/xGO4jYuqPLpdwJIoqn4jIXqO24rLmXG71qTy4QPy7CmQ9xXbML0EkcJk3ABbXR6rgv4gTmYl8nQP+nDIyzG4xyL6v/qE+hGEwewIQupB0tG3cIR9GfceozAdNxpd+u4jmfYkmOlvMRwfMEDdLQx/gD6RP4AAAAASUVORK5CYII=',
            title: notifTitle,
            message: notifMessage
          });
        } catch (e) {
          console.warn('Notification failed:', e);
        }
        
        console.log(`[Background] ${taskType} task completed for tab ${tabId}`);
        return;
        
      } else if (status.status === 'error') {
        // 任务失败
        throw new Error(status.error || '处理失败');
        
      } else {
        // 任务仍在处理中，更新进度信息
        await updateTaskStatus(tabId, taskType, {
          status: 'processing',
          message: status.progress || '正在处理中...',
          backendTaskId: backendTaskId,
          timestamp: Date.now()
        });
      }
      
      // 等待下一次轮询
      await new Promise(resolve => setTimeout(resolve, pollInterval));
      
    } catch (error) {
      console.error(`[Background] Poll error:`, error);
      
      await updateTaskStatus(tabId, taskType, {
        status: 'error',
        error: error.message,
        timestamp: Date.now()
      });
      
      // 发送错误通知
      try {
        const notifTitle = taskType === 'qa' ? 'AI 问答失败' : '简历优化失败';
        chrome.notifications.create({
          type: 'basic',
          iconUrl: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAA7AAAAOwBeShxvQAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAAGkSURBVFiFzdW/L0RBEMDxz104iR+Fw3FFKF0h0fgRiVqjodD4KzQKEo1GI9GIQkMoNEpKhYZIJBqNxh+w390ru/u+u+y+e0Qx2bzc7Ozszuzb3Q1KKQX/LwI/a2Z2AldLBNbiHnZiKxZiWq4GcBtXcBEPugiYyTH8wG4cxCpMxjxcx3L0FgHvMQ17s2Z2E1NYlUe/jxHYhzuYneGDWI+D+IDVGIPPWIb+vAHVqBEAT7C0wuNVrMUjzOtAsKS+5YMu5JrgQ7gGt9swM8cS/A5OYQhmYnuG1+IBVmAprmFjxr8CdyIh/MATDEE/3sWiHJdWlPIEfNe8xOhMwEa8xSoMZJxBv/p0EvdxHV2IeDDGohTnMSETQzAfB3C4yoZnOIsxqjz6FvxEewJexGZMxaT8/xGO4jYuqPLpdwJIoqn4jIXqO24rLmXG71qTy4QPy7CmQ9xXbML0EkcJk3ABbXR6rgv4gTmYl8nQP+nDIyzG4xyL6v/qE+hGEwewIQupB0tG3cIR9GfceozAdNxpd+u4jmfYkmOlvMRwfMEDdLQx/gD6RP4AAAAASUVORK5CYII=',
          title: notifTitle,
          message: error.message
        });
      } catch (e) {
        console.warn('Notification failed:', e);
      }
      
      return;
    }
  }
  
  // 超时
  await updateTaskStatus(tabId, taskType, {
    status: 'error',
    error: '处理超时（超过3分钟），请检查后端日志',
    timestamp: Date.now()
  });
}

// 更新任务状态到 storage
async function updateTaskStatus(tabId, taskType, data) {
  const key = `task_${tabId}_${taskType}`;
  await chrome.storage.local.set({ [key]: data });
}

// 获取任务状态
async function getTaskStatus(tabId, taskType = 'resume') {
  const key = `task_${tabId}_${taskType}`;
  const result = await chrome.storage.local.get(key);
  return result[key] || null;
}

// 清除任务
async function clearTask(tabId, taskType = 'resume') {
  const key = `task_${tabId}_${taskType}`;
  await chrome.storage.local.remove(key);
}

// 处理 AI 问答任务
async function handleAnswerQuestions(tabId, pageText, sourceUrl) {
  console.log(`[Background] Starting QA for tab ${tabId}`);
  
  // 更新状态为处理中
  await updateTaskStatus(tabId, 'qa', {
    status: 'processing',
    message: '正在提交任务到后端...',
    timestamp: Date.now()
  });
  
  try {
    // 调用后端 API
    const formData = new FormData();
    formData.append('page_text', pageText);
    formData.append('source_url', sourceUrl);
    
    // 使用 AbortController 设置超时（30秒提交超时）
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 30000);
    
    console.log(`[Background] Sending QA request to API...`);
    
    const response = await fetch(`${API_BASE}/api/answer-questions`, {
      method: 'POST',
      body: formData,
      signal: controller.signal
    });
    
    clearTimeout(timeoutId);
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `HTTP ${response.status}`);
    }
    
    console.log(`[Background] Received QA response, parsing JSON...`);
    const taskResponse = await response.json();
    
    // API 返回任务状态 (status: 'pending', task_id: 'xxx')
    const backendTaskId = taskResponse.task_id;
    console.log(`[Background] QA Task submitted: ${backendTaskId}`);
    
    // 更新状态
    await updateTaskStatus(tabId, 'qa', {
      status: 'processing',
      message: '正在分析页面问题并生成答案...',
      backendTaskId: backendTaskId,
      timestamp: Date.now()
    });
    
    // 开始轮询后端任务状态
    await pollTaskStatus(tabId, backendTaskId, 'qa');
    
  } catch (error) {
    console.error(`[Background] QA Error for tab ${tabId}:`, error);
    
    // 处理超时错误
    let errorMessage = error.message;
    if (error.name === 'AbortError') {
      errorMessage = '请求超时（超过30秒），请检查后端服务是否运行正常';
    }
    
    // 更新状态为错误
    await updateTaskStatus(tabId, 'qa', {
      status: 'error',
      error: errorMessage,
      timestamp: Date.now()
    });
    
    // 发送错误通知
    try {
      chrome.notifications.create({
        type: 'basic',
        iconUrl: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAABHNCSVQICAgIfAhkiAAAAAlwSFlzAAAA7AAAAOwBeShxvQAAABl0RVh0U29mdHdhcmUAd3d3Lmlua3NjYXBlLm9yZ5vuPBoAAAGkSURBVFiFzdW/L0RBEMDxz104iR+Fw3FFKF0h0fgRiVqjodD4KzQKEo1GI9GIQkMoNEpKhYZIJBqNxh+w390ru/u+u+y+e0Qx2bzc7Ozszuzb3Q1KKQX/LwI/a2Z2AldLBNbiHnZiKxZiWq4GcBtXcBEPugiYyTH8wG4cxCpMxjxcx3L0FgHvMQ17s2Z2E1NYlUe/jxHYhzuYneGDWI+D+IDVGIPPWIb+vAHVqBEAT7C0wuNVrMUjzOtAsKS+5YMu5JrgQ7gGt9swM8cS/A5OYQhmYnuG1+IBVmAprmFjxr8CdyIh/MATDEE/3sWiHJdWlPIEfNe8xOhMwEa8xSoMZJxBv/p0EvdxHV2IeDDGohTnMSETQzAfB3C4yoZnOIsxqjz6FvxEewJexGZMxaT8/xGO4jYuqPLpdwJIoqn4jIXqO24rLmXG71qTy4QPy7CmQ9xXbML0EkcJk3ABbXR6rgv4gTmYl8nQP+nDIyzG4xyL6v/qE+hGEwewIQupB0tG3cIR9GfceozAdNxpd+u4jmfYkmOlvMRwfMEDdLQx/gD6RP4AAAAASUVORK5CYII=',
        title: 'AI 问答失败',
        message: errorMessage
      });
    } catch (e) {
      console.warn('Notification failed:', e);
    }
  }
}

// 清理过期任务（超过 24 小时）
async function cleanupOldTasks() {
  const allData = await chrome.storage.local.get(null);
  const now = Date.now();
  const maxAge = 24 * 60 * 60 * 1000; // 24 小时
  
  const keysToRemove = [];
  for (const [key, value] of Object.entries(allData)) {
    // 匹配 task_{tabId}_{taskType} 格式
    if (key.startsWith('task_') && value.timestamp) {
      if (now - value.timestamp > maxAge) {
        keysToRemove.push(key);
      }
    }
  }
  
  if (keysToRemove.length > 0) {
    await chrome.storage.local.remove(keysToRemove);
    console.log(`[Background] Cleaned up ${keysToRemove.length} old tasks`);
  }
}

// 定期清理过期任务
chrome.alarms.create('cleanup', { periodInMinutes: 60 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'cleanup') {
    cleanupOldTasks();
  }
});

// 启动时清理一次
cleanupOldTasks();

console.log('[Background] Service Worker started');
