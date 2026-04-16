"""
职位申请日志模块 - 记录每次简历修改的详细信息

功能：
- 记录每次申请的公司名、岗位名、网页URL、修改详情
- 持久化存储到 JSON 文件
- 支持按公司名查询历史记录
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, asdict, field

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import LOG_FILE_PATH, OUTPUT_DIR


@dataclass
class ModificationRecord:
    """单条修改记录"""
    target: str              # 原文本
    replacement: str         # 替换后文本
    reason: str              # 修改原因
    success: bool            # 是否成功
    error_message: Optional[str] = None  # 失败原因


@dataclass
class ApplicationLog:
    """职位申请日志"""
    timestamp: str                          # 申请时间
    company_name: str                       # 公司名称
    job_title: str                          # 岗位名称
    source_url: str                         # 来源网页URL
    job_summary: str                        # 岗位要求总结
    match_score: int                        # 匹配度评分
    modifications: List[ModificationRecord] # 修改列表
    success_count: int                      # 成功修改数
    total_count: int                        # 总修改数
    task_id: Optional[str] = None           # 任务ID（用于下载）
    word_path: Optional[str] = None         # 生成的 Word 文件路径
    pdf_path: Optional[str] = None          # 生成的 PDF 文件路径
    word_filename: Optional[str] = None     # Word 文件名
    pdf_filename: Optional[str] = None      # PDF 文件名
    suggestions: List[str] = field(default_factory=list)  # AI 建议
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        return data


class JobLogManager:
    """日志管理器"""
    
    def __init__(self, log_file: Optional[str] = None):
        """
        初始化日志管理器
        
        Args:
            log_file: 日志文件路径，默认使用配置
        """
        self.log_file = Path(log_file or LOG_FILE_PATH)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # 备份目录
        self.backup_dir = self.log_file.parent / "log_backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 确保日志文件存在
        if not self.log_file.exists():
            self._save_logs([])
    
    def _load_logs(self) -> List[Dict[str, Any]]:
        """加载所有日志"""
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []
    
    def _backup_logs(self) -> Optional[Path]:
        """
        备份当前日志文件
        
        Returns:
            备份文件路径，如果无需备份则返回 None
        """
        if not self.log_file.exists():
            return None
        
        # 检查文件是否有内容
        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content or content == '[]':
                    return None  # 空文件无需备份
        except Exception:
            return None
        
        # 生成备份文件名：application_logs_YYYYMMDD_HHMMSS.json
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{self.log_file.stem}_{timestamp}{self.log_file.suffix}"
        backup_path = self.backup_dir / backup_filename
        
        # 复制文件
        import shutil
        shutil.copy2(self.log_file, backup_path)
        print(f"[JobLog] 已备份日志到: {backup_path}")
        
        # 清理旧备份（保留最近10个）
        self._cleanup_old_backups(keep=10)
        
        return backup_path
    
    def _cleanup_old_backups(self, keep: int = 10) -> None:
        """
        清理旧的备份文件，只保留最近的N个
        
        Args:
            keep: 保留的备份数量
        """
        if not self.backup_dir.exists():
            return
        
        # 获取所有备份文件
        backups = sorted(
            self.backup_dir.glob(f"{self.log_file.stem}_*{self.log_file.suffix}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        # 删除多余的备份
        for old_backup in backups[keep:]:
            try:
                old_backup.unlink()
                print(f"[JobLog] 已删除旧备份: {old_backup.name}")
            except Exception as e:
                print(f"[JobLog] 删除旧备份失败: {old_backup.name}, {e}")
    
    def _save_logs(self, logs: List[Dict[str, Any]]) -> None:
        """保存所有日志（自动备份）"""
        # 先备份现有日志
        self._backup_logs()
        
        # 保存新日志
        with open(self.log_file, 'w', encoding='utf-8') as f:
            json.dump(logs, f, ensure_ascii=False, indent=2)
    
    def save_log(self, log: ApplicationLog) -> None:
        """
        保存一条申请日志
        
        Args:
            log: 申请日志对象
        """
        logs = self._load_logs()
        logs.append(log.to_dict())
        self._save_logs(logs)
        print(f"[JobLog] 已保存申请记录: {log.company_name} - {log.job_title}")
    
    def get_logs(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        获取所有日志
        
        Args:
            limit: 返回最近N条记录，None表示全部
            
        Returns:
            日志列表（最新的在前）
        """
        logs = self._load_logs()
        # 按时间倒序排列
        logs.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        
        if limit:
            return logs[:limit]
        return logs
    
    def get_logs_by_company(self, company_name: str) -> List[Dict[str, Any]]:
        """
        按公司名查询日志
        
        Args:
            company_name: 公司名（模糊匹配）
            
        Returns:
            匹配的日志列表
        """
        logs = self._load_logs()
        company_lower = company_name.lower()
        
        matched = [
            log for log in logs 
            if company_lower in log.get('company_name', '').lower()
        ]
        
        # 按时间倒序排列
        matched.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
        return matched
    
    def get_log_by_id(self, timestamp: str) -> Optional[Dict[str, Any]]:
        """
        按时间戳获取单条日志
        
        Args:
            timestamp: 日志时间戳
            
        Returns:
            日志记录或 None
        """
        logs = self._load_logs()
        for log in logs:
            if log.get('timestamp') == timestamp:
                return log
        return None
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息
        
        Returns:
            统计数据
        """
        logs = self._load_logs()
        
        if not logs:
            return {
                "total_applications": 0,
                "companies": [],
                "average_match_score": 0,
                "success_rate": 0
            }
        
        companies = list(set(log.get('company_name', 'Unknown') for log in logs))
        total_score = sum(log.get('match_score', 0) for log in logs)
        total_mods = sum(log.get('total_count', 0) for log in logs)
        success_mods = sum(log.get('success_count', 0) for log in logs)
        
        return {
            "total_applications": len(logs),
            "companies": companies,
            "average_match_score": round(total_score / len(logs), 1),
            "success_rate": round(success_mods / total_mods * 100, 1) if total_mods > 0 else 0
        }


# 全局日志管理器实例
_log_manager: Optional[JobLogManager] = None


def get_log_manager() -> JobLogManager:
    """获取全局日志管理器"""
    global _log_manager
    if _log_manager is None:
        _log_manager = JobLogManager()
    return _log_manager


def save_application_log(
    company_name: str,
    job_title: str,
    source_url: str,
    job_summary: str,
    match_score: int,
    modifications: List[Dict[str, Any]],
    task_id: Optional[str] = None,
    word_path: Optional[str] = None,
    pdf_path: Optional[str] = None,
    word_filename: Optional[str] = None,
    pdf_filename: Optional[str] = None,
    suggestions: Optional[List[str]] = None
) -> ApplicationLog:
    """
    便捷函数：保存申请日志
    
    Args:
        company_name: 公司名
        job_title: 岗位名
        source_url: 来源网页URL
        job_summary: 岗位总结
        match_score: 匹配分数
        modifications: 修改列表
        task_id: 任务ID（用于下载）
        word_path: Word文件路径
        pdf_path: PDF文件路径
        word_filename: Word文件名
        pdf_filename: PDF文件名
        suggestions: AI建议
        
    Returns:
        保存的日志对象
    """
    # 转换修改记录
    mod_records = [
        ModificationRecord(
            target=m.get('target', ''),
            replacement=m.get('replacement', ''),
            reason=m.get('reason', ''),
            success=m.get('success', False),
            error_message=m.get('error_message')
        )
        for m in modifications
    ]
    
    success_count = sum(1 for m in mod_records if m.success)
    
    log = ApplicationLog(
        timestamp=datetime.now().isoformat(),
        company_name=company_name,
        job_title=job_title,
        source_url=source_url,
        job_summary=job_summary,
        match_score=match_score,
        modifications=mod_records,
        success_count=success_count,
        total_count=len(mod_records),
        task_id=task_id,
        word_path=word_path,
        pdf_path=pdf_path,
        word_filename=word_filename,
        pdf_filename=pdf_filename,
        suggestions=suggestions or []
    )
    
    get_log_manager().save_log(log)
    return log


if __name__ == "__main__":
    # 测试代码
    manager = JobLogManager()
    
    # 创建测试日志
    test_log = ApplicationLog(
        timestamp=datetime.now().isoformat(),
        company_name="Test Company",
        job_title="AI Engineer",
        source_url="https://example.com/job/123",
        job_summary="Looking for AI developer with Python experience",
        match_score=85,
        modifications=[
            ModificationRecord(
                target="3 years experience",
                replacement="5 years experience",
                reason="Match job requirement",
                success=True
            )
        ],
        success_count=1,
        total_count=1,
        suggestions=["Consider adding more AI projects"]
    )
    
    manager.save_log(test_log)
    print("\n所有日志:", manager.get_logs())
    print("\n统计信息:", manager.get_stats())
