### Integrando o time front+back

Instale o python 3.11.9 e o pip (gerenciador de dependencias)

Clone o repositório e abra-o na IDE

Crie um ambiente python (da pra fazer com o VSCode sem linhas de comando):
```
python -m venv .venv
```

Ative o ambiente:
```
.venv\Scripts\activate
```
Caso ativo, vai aparecer na frente do path no terminal.

Instale todas as dependencias:
```
pip install -r requirements.txt
```

Para testar, caso esteja em um projeto separado chame com o path completo:
```
C:...\TalkingHands\.venv\Scripts\python.exe C:...\TalkingHands\src\main.py <args>
```

Caso esteja no mesmo projeto que o python:
Ative o ambiente e execute
```
python src/main.py <args>
```

Use o arg -h para exibir a documentação da CLI

### Ocultar arquivos cache e init no VSCode
Vá para Settings > procure por files.exclude > adicione:

**/__pycache__

**/__init__.py