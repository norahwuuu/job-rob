"""
PDF 导出器 - 将 Word 文档转换为 PDF
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import Optional
import platform


class PDFExporter:
    """
    PDF 导出器
    
    在 Windows 上使用 docx2pdf（调用 Word COM 接口）
    在其他平台上使用 LibreOffice
    """
    
    def __init__(self):
        """初始化导出器"""
        self.system = platform.system()
        self._check_dependencies()
    
    def _check_dependencies(self):
        """检查依赖是否满足"""
        if self.system == "Windows":
            # Windows 使用 docx2pdf
            try:
                import docx2pdf
                self.converter = "docx2pdf"
            except ImportError:
                # 尝试使用 LibreOffice
                if self._check_libreoffice():
                    self.converter = "libreoffice"
                else:
                    raise RuntimeError(
                        "未找到 PDF 转换器。请安装 docx2pdf (pip install docx2pdf) "
                        "或安装 LibreOffice。"
                    )
        else:
            # Linux/Mac 使用 LibreOffice
            if self._check_libreoffice():
                self.converter = "libreoffice"
            else:
                raise RuntimeError(
                    "未找到 LibreOffice。请安装 LibreOffice 以支持 PDF 转换。"
                )
    
    def _check_libreoffice(self) -> bool:
        """检查 LibreOffice 是否可用"""
        try:
            # 尝试不同的命令名
            for cmd in ["libreoffice", "soffice", "soffice.exe"]:
                try:
                    result = subprocess.run(
                        [cmd, "--version"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        self.libreoffice_cmd = cmd
                        return True
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            return False
        except Exception:
            return False
    
    def convert(self, docx_path: str, output_path: Optional[str] = None) -> str:
        """
        将 Word 文档转换为 PDF
        
        Args:
            docx_path: Word 文档路径
            output_path: 输出 PDF 路径（可选，默认与输入同名）
            
        Returns:
            生成的 PDF 文件路径
        """
        docx_path = Path(docx_path).resolve()
        
        if not docx_path.exists():
            raise FileNotFoundError(f"文件不存在: {docx_path}")
        
        # 确定输出路径
        if output_path:
            pdf_path = Path(output_path).resolve()
        else:
            pdf_path = docx_path.with_suffix('.pdf')
        
        # 确保输出目录存在
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 执行转换
        if self.converter == "docx2pdf":
            return self._convert_with_docx2pdf(docx_path, pdf_path)
        else:
            return self._convert_with_libreoffice(docx_path, pdf_path)
    
    def _convert_with_docx2pdf(self, docx_path: Path, pdf_path: Path) -> str:
        """使用 docx2pdf 转换（Windows）"""
        import sys
        from docx2pdf import convert
        
        # 在线程中使用COM需要先初始化
        import pythoncom
        pythoncom.CoInitialize()
        
        try:
            print("📄 正在导出 PDF（可能需要 3-5 秒）...", flush=True)
            
            # docx2pdf.convert() 需要字符串路径
            convert(str(docx_path), str(pdf_path))
            
            if not pdf_path.exists():
                raise RuntimeError(f"PDF 转换失败，输出文件不存在: {pdf_path}")
            
            print("✅ PDF 导出完成", flush=True)
            return str(pdf_path)
        finally:
            # 确保释放COM
            pythoncom.CoUninitialize()
    
    def _convert_with_libreoffice(self, docx_path: Path, pdf_path: Path) -> str:
        """使用 LibreOffice 转换"""
        output_dir = pdf_path.parent
        
        # LibreOffice 命令
        cmd = [
            self.libreoffice_cmd,
            "--headless",
            "--convert-to", "pdf",
            "--outdir", str(output_dir),
            str(docx_path)
        ]
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 2分钟超时
            )
            
            if result.returncode != 0:
                raise RuntimeError(f"LibreOffice 转换失败: {result.stderr}")
            
            # LibreOffice 生成的文件名是原文件名.pdf
            generated_pdf = output_dir / (docx_path.stem + ".pdf")
            
            # 如果目标路径不同，重命名
            if generated_pdf != pdf_path:
                if pdf_path.exists():
                    pdf_path.unlink()
                generated_pdf.rename(pdf_path)
            
            if not pdf_path.exists():
                raise RuntimeError(f"PDF 转换失败，输出文件不存在: {pdf_path}")
            
            return str(pdf_path)
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("LibreOffice 转换超时")
    
    def batch_convert(self, docx_paths: list, output_dir: Optional[str] = None) -> list:
        """
        批量转换
        
        Args:
            docx_paths: Word 文档路径列表
            output_dir: 输出目录（可选）
            
        Returns:
            生成的 PDF 文件路径列表
        """
        results = []
        
        for docx_path in docx_paths:
            try:
                if output_dir:
                    pdf_name = Path(docx_path).stem + ".pdf"
                    output_path = Path(output_dir) / pdf_name
                else:
                    output_path = None
                
                pdf_path = self.convert(docx_path, output_path)
                results.append({"input": docx_path, "output": pdf_path, "success": True})
            except Exception as e:
                results.append({"input": docx_path, "error": str(e), "success": False})
        
        return results


def export_to_pdf(docx_path: str, output_path: Optional[str] = None) -> str:
    """
    便捷函数：导出为 PDF
    
    Args:
        docx_path: Word 文档路径
        output_path: 输出路径（可选）
        
    Returns:
        PDF 文件路径
    """
    exporter = PDFExporter()
    return exporter.convert(docx_path, output_path)


if __name__ == "__main__":
    # 测试代码
    import sys
    
    if len(sys.argv) > 1:
        docx_path = sys.argv[1]
    else:
        docx_path = "../cv.docx"
    
    try:
        print(f"转换文件: {docx_path}")
        exporter = PDFExporter()
        print(f"使用转换器: {exporter.converter}")
        
        pdf_path = exporter.convert(docx_path)
        print(f"成功生成 PDF: {pdf_path}")
        
        # 获取文件大小
        size = os.path.getsize(pdf_path) / 1024
        print(f"文件大小: {size:.1f} KB")
        
    except Exception as e:
        print(f"转换失败: {e}")
        import traceback
        traceback.print_exc()
