
import ast


class PythonParser:
    def parse(self, source):
        try:
            tree = ast.parse(source)
            return {
                "success": True,
                "tree": tree,
                "error": None,
            }

        except SyntaxError as error:
            return {
                "success": False,
                "tree": None,
                "error": {
                    "message": error.msg,
                    "line": error.lineno,
                    "column": error.offset,
                    "text": error.text,
                },
            }

        except Exception as error:
            return {
                "success": False,
                "tree": None,
                "error": {
                    "message": str(error),
                    "line": None,
                    "column": None,
                    "text": None,
                },
            }