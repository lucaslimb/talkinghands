## Launcher team

### Integrando os projetos launcher+python 

#### COM BUILDED .EXE

Apenas execute o exe a partir do seu path com o args desejeados
```bash
THEngine.exe <args>
```

#### SEM BUILDED .EXE

Instale o python 3.11.9 e o pip (gerenciador de dependencias)

Clone o repositório e abra-o na IDE

Crie um ambiente python (da pra fazer com o VSCode sem linhas de comando):
```bash
python -m venv .venv
```

Ative o ambiente:
```bash
.venv\Scripts\activate
```
Caso ativo, vai aparecer na frente do path no terminal.

Instale todas as dependencias:
```bash
pip install -r requirements.txt
```

Para testar, caso esteja em um projeto separado chame com o path completo:
```bash
C:...\TalkingHands\.venv\Scripts\python.exe C:...\TalkingHands\src\main.py <args>
```

Caso esteja no mesmo projeto que o python:
Ative o ambiente e execute
```bash
python src/main.py <args>
```

Use o arg -h para exibir a documentação da CLI

## Python team

### Ocultar arquivos cache e init no VSCode
Vá para Settings > procure por files.exclude > adicione:

**/__pycache__

**/__init__.py

### Buildar um exe

Se não tiver instalado o pyinstaller, rode:
```bash
pip install pyinstaller
```

Rode o build.py num terminal com os seguintes argumentos (vai excluir a build anterior e substituir pela nova):
```bash
cd "c:...\Talking Hands" ; rmdir /s /q dist build 2>$null; .\.venv\Scripts\python.exe build.py
```

Depois de buildar, pode deletar tudo em build/ enquanto o .exe vai estar em dist/

Code signing (verificar se é necessário)
```bash
signtool sign /f mycert.pfx /p password /d "Talking Hands" dist/THEngine.exe
```