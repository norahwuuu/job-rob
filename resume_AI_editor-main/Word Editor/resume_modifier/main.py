"""
简历自动修改程序 - 主入口

使用方法:
    python -m resume_modifier.main --resume "简历.docx" --job "岗位描述" --output "output"
"""

import click
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from typing import Optional
import json
from datetime import datetime

from .resume_parser import ResumeParser
from .ai_analyzer import AIAnalyzer
from .content_modifier import ContentModifier, ModificationInstruction
from .pdf_exporter import PDFExporter
from .resume_validator import validate_resume_docx
from .resume_auto_fix import apply_resume_auto_fixes

console = Console()


def run_output_validation(word_path: str, verbose: bool) -> dict:
    """校验生成的 Word；不通过则自动修复并复验。"""
    validation = validate_resume_docx(word_path)
    if not validation.get("ok"):
        fix_report = apply_resume_auto_fixes(word_path, verbose=verbose)
        validation = validate_resume_docx(word_path)
        validation["auto_fix"] = fix_report
    return validation


def print_validation_report(validation: dict, verbose: bool) -> None:
    if not verbose:
        return
    if validation.get("warnings"):
        console.print("  [yellow]⚠ 简历自检（生成后，含自动修复后仍存在的问题）:[/yellow]")
        for w in validation["warnings"]:
            console.print(f"    [yellow]- {w}[/yellow]")
    elif validation.get("ok"):
        msg = "✓ 简历自检：未发现重复章节标题或明显要点格式问题"
        af = validation.get("auto_fix") or {}
        if af.get("removed_duplicate_headings") or af.get("bullet_lead_fixes"):
            msg += "（已自动修复版式）"
        console.print(f"  [dim]{msg}[/dim]")


def is_file_locked(file_path: Path) -> bool:
    """检查文件是否被锁定（被其他程序打开）"""
    if not file_path.exists():
        return False
    
    # 检查是否有 Word 临时锁文件
    lock_file = file_path.parent / f"~${file_path.name}"
    if lock_file.exists():
        return True
    
    # 尝试以写入模式打开文件来检测是否被锁定
    try:
        with open(file_path, 'r+b'):
            pass
        return False
    except (IOError, PermissionError):
        return True


def get_available_filename(base_path: Path) -> Path:
    """获取可用的文件名，如果文件被锁定则添加时间戳"""
    if not is_file_locked(base_path):
        return base_path
    
    # 文件被锁定，添加时间戳
    stem = base_path.stem
    suffix = base_path.suffix
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    new_name = f"{stem}_{timestamp}{suffix}"
    return base_path.parent / new_name


def process_resume(
    resume_path: str,
    job_description: str,
    output_dir: str,
    output_name: Optional[str] = None,
    api_key: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    skip_pdf: bool = False,
    verbose: bool = False,
    debug: bool = False
) -> dict:
    """
    处理简历的核心函数
    
    Args:
        resume_path: 简历 Word 文档路径
        job_description: 岗位描述
        output_dir: 输出目录
        output_name: 输出文件名（不含扩展名）
        api_key: API 密钥（按 provider 使用）
        provider: AI 提供商（openai / gemini）
        model: 模型名称
        skip_pdf: 是否跳过 PDF 生成
        verbose: 是否输出详细信息
        debug: 是否输出调试信息（显示AI返回的target和文档实际内容对比）
        
    Returns:
        处理结果字典
    """
    # 统一结果结构：CLI 与 API 都复用这个返回体
    result = {
        "success": False,
        "word_path": None,
        "pdf_path": None,
        "modifications": [],
        "suggestions": [],
        "match_score": 0,
        "job_summary": None,
        "company_name": "Unknown Company",
        "job_title": "Unknown Position",
        "error": None,
        "validation": None,
    }
    
    try:
        # 1) 解析简历：把 docx 转成结构化文本，供后续 AI 与替换逻辑使用
        if verbose:
            console.print("[blue]步骤 1/4:[/blue] 解析简历...")
        
        parser = ResumeParser(resume_path)
        parsed = parser.parse()
        resume_text = parser.get_text_for_ai()
        
        if debug:
            console.print("\n[cyan]===== DEBUG: 简历原始文本 =====[/cyan]")
            console.print(resume_text[:2000] + "..." if len(resume_text) > 2000 else resume_text)
            console.print("[cyan]================================[/cyan]\n")
        
        if verbose:
            console.print(f"  ✓ 解析完成，共 {len(parsed.all_blocks)} 个文本块")
        
        # 2) AI 分析：根据 JD 生成可执行的修改指令（target/replacement/match_type）
        if verbose:
            console.print("[blue]步骤 2/4:[/blue] AI 分析岗位要求（可能需要 5-10 秒）...")
        
        analyzer = AIAnalyzer(api_key=api_key, provider=provider, model=model)
        analysis = analyzer.analyze(job_description, resume_text)
        
        if verbose:
            console.print(f"  ✓ 分析完成，生成 {len(analysis.modifications)} 条修改指令")
            console.print(f"  ✓ 预期匹配度: {analysis.match_score}%")
        
        if debug:
            console.print("\n[cyan]===== DEBUG: AI生成的修改指令 =====[/cyan]")
            for i, m in enumerate(analysis.modifications, 1):
                console.print(f"  {i}. target: '{m.target}'")
                console.print(f"     replacement: '{m.replacement}'")
                console.print(f"     match_type: {m.match_type}")
            console.print("[cyan]====================================[/cyan]\n")
        
        result["job_summary"] = analysis.job_summary
        result["match_score"] = analysis.match_score
        result["suggestions"] = analysis.suggestions
        result["company_name"] = analysis.company_name
        result["job_title"] = analysis.job_title
        
        # 3) 修改文档：将 AI 指令转换为内容修改器需要的指令类型并执行
        if verbose:
            console.print("[blue]步骤 3/4:[/blue] 修改简历...")
        
        modifier = ContentModifier(resume_path)
        
        # 转换指令格式
        instructions = [
            ModificationInstruction(
                target=m.target,
                replacement=m.replacement,
                reason=m.reason,
                priority=m.priority,
                match_type=m.match_type
            )
            for m in analysis.modifications
        ]
        
        success_count = modifier.apply_modifications(instructions)
        
        if verbose:
            console.print(f"  ✓ 成功修改 {success_count}/{len(instructions)} 处")
            
            # 显示失败的修改详情
            failed_logs = [log for log in modifier.get_logs() if not log.success]
            if failed_logs:
                console.print(f"  [yellow]⚠ {len(failed_logs)} 处修改未能应用:[/yellow]")
                for log in failed_logs:
                    console.print(f"    [dim]- 目标: '{log.target[:40]}...'[/dim]")
                    console.print(f"      [red]{log.error_message}[/red]")
            
            # 调试模式：显示runs详情
            if debug:
                console.print("\n[cyan]===== DEBUG: Runs 替换详情 =====[/cyan]")
                success_logs = [log for log in modifier.get_logs() if log.success and log.debug_info]
                for log in success_logs:
                    console.print(f"\n[yellow]Target:[/yellow] {log.target[:50]}...")
                    console.print(f"[green]Replacement:[/green] {log.replacement[:50]}...")
                    if log.debug_info:
                        console.print(f"[dim]Paragraph text: '{log.debug_info.get('before_text', '')[:80]}'[/dim]")
                        console.print(f"[dim]Before runs: {log.debug_info.get('before_runs', [])}[/dim]")
                        console.print(f"[dim]After runs:  {log.debug_info.get('after_runs', [])}[/dim]")
                        console.print(f"[dim]Match range: {log.debug_info.get('match_range', '')}[/dim]")
                        console.print(f"[dim]New text: '{log.debug_info.get('new_paragraph_text', '')[:80]}'[/dim]")
                console.print("[cyan]================================[/cyan]\n")
        
        # Use detailed modification results with success status
        result["modifications"] = modifier.get_modification_results()
        result["modification_logs"] = [
            {"target": log.target, "success": log.success, "error": log.error_message}
            for log in modifier.get_logs()
        ]
        
        # 保存 Word 文档（优先使用指定文件名；若被占用则自动改名）
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        if output_name:
            word_filename = f"{output_name}.docx"
        else:
            word_filename = f"{Path(resume_path).stem}_modified.docx"
        
        word_path = output_path / word_filename
        
        # 检查文件是否被锁定，如果被锁定则使用带时间戳的文件名
        word_path = get_available_filename(word_path)
        if word_path != (output_path / word_filename):
            if verbose:
                console.print(f"  [yellow]⚠ 原文件被锁定，将保存为: {word_path.name}[/yellow]")
        
        try:
            modifier.save(str(word_path))
        except PermissionError as e:
            # 如果仍然失败，尝试使用时间戳文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = Path(word_filename).stem
            new_filename = f"{stem}_{timestamp}.docx"
            word_path = output_path / new_filename
            if verbose:
                console.print(f"  [yellow]⚠ 文件保存失败，尝试使用新文件名: {word_path.name}[/yellow]")
            modifier.save(str(word_path))
        
        result["word_path"] = str(word_path)
        
        if verbose:
            console.print(f"  ✓ Word 文档已保存: {word_path}")

        try:
            result["validation"] = run_output_validation(str(word_path), verbose)
            print_validation_report(result["validation"], verbose)
        except Exception as ve:
            result["validation"] = {
                "ok": False,
                "duplicate_section_titles": [],
                "format_issue_hints": [],
                "warnings": [f"validation skipped: {ve}"],
                "section_count": 0,
            }
            if verbose:
                console.print(f"  [yellow]⚠ 简历自检失败（已跳过）: {ve}[/yellow]")
        
        # 4) 生成 PDF：失败不影响 Word 成果，错误会写入 result["pdf_error"]
        if not skip_pdf:
            if verbose:
                console.print("[blue]步骤 4/4:[/blue] 生成 PDF（可能需要 3-5 秒）...")
            
            try:
                exporter = PDFExporter()
                # 使用与 Word 文件相同的文件名（但扩展名为 .pdf）
                pdf_path = word_path.with_suffix('.pdf')
                exporter.convert(str(word_path), str(pdf_path))
                result["pdf_path"] = str(pdf_path)
                
                if verbose:
                    console.print(f"  ✓ PDF 已生成: {pdf_path}")
            except Exception as e:
                if verbose:
                    console.print(f"  [yellow]⚠ PDF 生成失败: {e}[/yellow]")
                result["pdf_error"] = str(e)
        
        result["success"] = True
        
    except Exception as e:
        result["error"] = str(e)
        if verbose:
            console.print(f"[red]✗ 处理失败: {e}[/red]")
            import traceback
            traceback.print_exc()
    
    return result


@click.command()
@click.option(
    '--resume', '-r',
    required=True,
    type=click.Path(exists=True),
    help='简历 Word 文档路径'
)
@click.option(
    '--job', '-j',
    required=True,
    help='岗位描述（文本或文件路径）'
)
@click.option(
    '--output', '-o',
    default='./output',
    help='输出目录（默认: ./output）'
)
@click.option(
    '--name', '-n',
    default=None,
    help='输出文件名（不含扩展名）'
)
@click.option(
    '--api-key', '-k',
    envvar='OPENAI_API_KEY',
    help='OpenAI API 密钥（也可通过环境变量设置）'
)
@click.option(
    '--skip-pdf',
    is_flag=True,
    help='跳过 PDF 生成'
)
@click.option(
    '--json-output',
    is_flag=True,
    help='以 JSON 格式输出结果'
)
@click.option(
    '--verbose', '-v',
    is_flag=True,
    help='详细输出'
)
@click.option(
    '--debug', '-d',
    is_flag=True,
    help='调试模式：显示runs替换详情'
)
def main(resume, job, output, name, api_key, skip_pdf, json_output, verbose, debug):
    """
    简历自动修改程序
    
    根据岗位描述自动优化简历，提高 HR 筛选通过率。
    
    示例:
        python -m resume_modifier.main -r 简历.docx -j "需要AI开发工程师，工作地点北京"
    """
    
    # 如果 job 是文件路径，读取文件内容
    job_path = Path(job)
    if job_path.exists() and job_path.is_file():
        job_description = job_path.read_text(encoding='utf-8')
    else:
        job_description = job
    
    if not json_output and not verbose:
        verbose = True  # 默认显示详细信息
    
    if not json_output:
        console.print(Panel.fit(
            "[bold blue]简历自动修改程序[/bold blue]\n"
            "基于 AI 分析岗位要求，智能优化简历",
            border_style="blue"
        ))
        console.print()
    
    # 处理简历
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        disable=json_output
    ) as progress:
        if not json_output:
            progress.add_task("处理中...", total=None)
        
        result = process_resume(
            resume_path=resume,
            job_description=job_description,
            output_dir=output,
            output_name=name,
            api_key=api_key,
            skip_pdf=skip_pdf,
            verbose=verbose and not json_output,
            debug=debug
        )
    
    # 输出结果
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        console.print()
        
        if result["success"]:
            # 成功面板
            console.print(Panel.fit(
                "[bold green]✓ 处理完成[/bold green]",
                border_style="green"
            ))
            
            # 输出文件表格
            table = Table(title="输出文件", show_header=True)
            table.add_column("类型", style="cyan")
            table.add_column("路径", style="green")
            
            if result["word_path"]:
                table.add_row("Word", result["word_path"])
            if result["pdf_path"]:
                table.add_row("PDF", result["pdf_path"])
            
            console.print(table)
            
            # 修改摘要
            if result["modifications"]:
                console.print()
                mod_table = Table(title=f"修改内容 ({len(result['modifications'])} 处)", show_header=True)
                mod_table.add_column("原文", style="red", max_width=30)
                mod_table.add_column("修改为", style="green", max_width=30)
                mod_table.add_column("原因", style="yellow", max_width=40)
                
                for mod in result["modifications"][:10]:  # 最多显示10条
                    mod_table.add_row(
                        mod["target"][:30] + "..." if len(mod["target"]) > 30 else mod["target"],
                        mod["replacement"][:30] + "..." if len(mod["replacement"]) > 30 else mod["replacement"],
                        mod["reason"]
                    )
                
                console.print(mod_table)
            
            # 建议
            if result.get("suggestions"):
                console.print()
                console.print("[bold yellow]额外建议:[/bold yellow]")
                for i, suggestion in enumerate(result["suggestions"], 1):
                    console.print(f"  {i}. {suggestion}")
            
            # 匹配度
            if result.get("match_score"):
                console.print()
                score = result["match_score"]
                color = "green" if score >= 70 else "yellow" if score >= 50 else "red"
                console.print(f"[bold]预期岗位匹配度: [{color}]{score}%[/{color}][/bold]")
        
        else:
            # 失败面板
            console.print(Panel.fit(
                f"[bold red]✗ 处理失败[/bold red]\n{result['error']}",
                border_style="red"
            ))
            raise SystemExit(1)


if __name__ == "__main__":
    main()
