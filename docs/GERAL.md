## Launcher team

### Integrando os projetos launcher+python 

#### COM BUILDED .EXE

Apenas execute o exe a partir do seu path com o args desejeados
```bash
THEngine.exe <args>
```

Use o arg -h para exibir a documentação da CLI

## Engine team

### Instalações 

1) Instale Python 3.11.9 !!
2) Crie um virtual environment no VSCode com o Python 3.11.9
3) Ative o virtual environment no terminal cmd:
```cmd
"C:\...\talkinghands\.venv\Scripts\activate.bat"
```
4) Instale o requirements.txt:
```cmd
pip install -r requirements.txt
```
5) Instale o openCV e Mediapipe separadamente, caso não instalados no passo 4:
```cmd
pip install opencv-python mediapipe==0.10.21
```

Se faltou informação da preparação do ambiente, pode adicionar aqui :)

### Testando

Com o virtual environment ativo, rode:
```
python src/main.py <args>
```
ou
```
python path/classe.py
```

### Ocultar arquivos cache e init no VSCode
Vá para Settings > procure por files.exclude > adicione:

**/__pycache__

**/__init__.py

### Buildar um exe para Windows

Se não tiver instalado o pyinstaller, rode:
```bash
pip install pyinstaller
```

Rode o build.py num terminal com os seguintes argumentos (vai excluir a build anterior se houver e substituir pela nova):
```bash
cd "c:...\Talking Hands" ; rmdir /s /q dist build 2>$null; .\.venv\Scripts\python.exe builders/build.py
```

dlls do FluidSynth precisam ser incluidas no bundle, então são baixadas automaticamente caso não estejam em assets/

Depois de buildar, pode deletar tudo em build/ enquanto que o diretorio gerado com o .exe vai estar em dist/ dividido em .exe e _internal (libs, dlls). Pra jogar em um repositório, zipamos tudo

Code signing (evita warnings de unkwnown publisher, mas a principio nao vai ser necessario)
```bash
signtool sign /f mycert.pfx /p password /d "Talking Hands" dist/THEngine.exe
```

### FYI

Se necessário, use o Github Copilot no VSCode com preferencia pelo modelo Claude Haiku 4.5 (se for copilot free) ou GPT-5.3-Codex (se for Pro)

Arquivos .sf2 (soundfonts) são enviados para o git com lfs, definido no .gitattributes
