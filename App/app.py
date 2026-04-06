import dash
from dash import html, dcc, Input, Output, State, callback_context
import psycopg
import os
from databricks import sdk
from psycopg import sql
from psycopg_pool import ConnectionPool
import mlflow

# Database connection setup
workspace_client = sdk.WorkspaceClient()
endpoint = os.getenv("PGENDPOINT", "")
connection_pool = None

# Agent endpoint setup
AGENT_MODEL = "mas-8f48e375-endpoint"

# MLflow experiment setup
mlflow.set_tracking_uri("databricks")
experiment_id = os.getenv("MLFLOW_EXPERIMENT_ID")
if experiment_id:
    mlflow.set_experiment(experiment_id=experiment_id)


@mlflow.trace(name="ask_agent")
def ask_agent(messages):
    """Send conversation history to the agent endpoint via raw API call."""
    try:
        body = {"input": messages}
        mlflow.log_text(str(body), "request_body.txt")

        response = workspace_client.api_client.do(
            "POST",
            f"/serving-endpoints/{AGENT_MODEL}/invocations",
            body=body
        )
        mlflow.log_text(str(response), "response_body.txt")

        # Try Responses API format first (output -> content -> text)
        output = response.get("output", [])
        if output:
            texts = []
            for item in output:
                for content in item.get("content", []):
                    text = content.get("text", "")
                    if text:
                        texts.append(text)
            if texts:
                return " ".join(texts)

        # Fallback: Chat Completions format (choices -> message -> content)
        choices = response.get("choices", [])
        if choices:
            return choices[0]["message"]["content"]

        mlflow.log_text(f"Unparsed response keys: {list(response.keys())}", "parse_debug.txt")
        return "No response received."
    except Exception as e:
        mlflow.log_text(str(e), "error.txt")
        return f"Error communicating with agent: {e}"


class OAuthConnection(psycopg.Connection):
    """Connection subclass that auto-refreshes OAuth credentials."""

    @classmethod
    def connect(cls, conninfo="", **kwargs):
        credential = workspace_client.postgres.generate_database_credential(
            endpoint=endpoint
        )
        kwargs["password"] = credential.token
        return super().connect(conninfo, **kwargs)


def get_connection_pool():
    """Get or create the connection pool."""
    global connection_pool
    if connection_pool is None:
        conn_string = (
            f"dbname={os.getenv('PGDATABASE')} "
            f"user={os.getenv('PGUSER')} "
            f"host={os.getenv('PGHOST')} "
            f"port={os.getenv('PGPORT')} "
            f"sslmode={os.getenv('PGSSLMODE', 'require')} "
            f"application_name={os.getenv('PGAPPNAME')}"
        )
        connection_pool = ConnectionPool(
            conn_string, connection_class=OAuthConnection, min_size=2, max_size=10
        )
    return connection_pool


def get_connection():
    """Get a connection from the pool."""
    return get_connection_pool().connection()


def get_schema_name():
    """Get the schema name in the format {PGAPPNAME}_schema_{PGUSER}."""
    pgappname = os.getenv("PGAPPNAME", "my_app")
    pguser = os.getenv("PGUSER", "").replace('-', '')
    return f"{pgappname}_schema_{pguser}"


def init_database():
    """Initialize database schema and table."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                schema_name = get_schema_name()

                cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema_name)))
                cur.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {}.todos (
                        id SERIAL PRIMARY KEY,
                        task TEXT NOT NULL,
                        completed BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """).format(sql.Identifier(schema_name)))
                conn.commit()
                return True
    except Exception as e:
        print(f"Database initialization error: {e}")
        return False


def add_todo(task):
    """Add a new todo item."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                schema = get_schema_name()
                cur.execute(sql.SQL("INSERT INTO {}.todos (task) VALUES (%s)").format(sql.Identifier(schema)), (task.strip(),))
                conn.commit()
                return True
    except Exception as e:
        print(f"Add todo error: {e}")
        return False


def get_todos():
    """Get all todo items."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                schema = get_schema_name()
                cur.execute(sql.SQL("SELECT id, task, completed, created_at FROM {}.todos ORDER BY created_at DESC").format(sql.Identifier(schema)))
                return cur.fetchall()
    except Exception as e:
        print(f"Get todos error: {e}")
        return []


def toggle_todo(todo_id):
    """Toggle the completed status of a todo item."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                schema = get_schema_name()
                cur.execute(sql.SQL("UPDATE {}.todos SET completed = NOT completed WHERE id = %s").format(sql.Identifier(schema)), (todo_id,))
                conn.commit()
                return True
    except Exception as e:
        print(f"Toggle todo error: {e}")
        return False


def delete_todo(todo_id):
    """Delete a todo item."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                schema = get_schema_name()
                cur.execute(sql.SQL("DELETE FROM {}.todos WHERE id = %s").format(sql.Identifier(schema)), (todo_id,))
                conn.commit()
                return True
    except Exception as e:
        print(f"Delete todo error: {e}")
        return False


def get_incidents():
    """Get all records from the andrij_demo.incidents table."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql.SQL(
                    "SELECT id, line_id, ts, severity, summary, details, status "
                    "FROM {}.incidents ORDER BY ts DESC"
                ).format(sql.Identifier("andrij_demo")))
                return cur.fetchall()
    except Exception as e:
        print(f"Get incidents error: {e}")
        return []


def render_chat_messages(chat_history):
    """Render chat messages as styled Dash components."""
    if not chat_history:
        return html.Div(
            "Ask the assistant a question to get started.",
            className='chat-placeholder'
        )

    messages = []
    for msg in chat_history:
        is_user = msg["role"] == "user"
        messages.append(html.Div(
            html.Div(msg["content"],
                      className=f'chat-bubble chat-bubble-{"user" if is_user else "assistant"}'),
            className=f'chat-row chat-row-{"user" if is_user else "assistant"}'
        ))
    return messages


# Initialize Dash app
app = dash.Dash(__name__)

# Initialize database
if not init_database():
    print("Failed to initialize database")

# App layout
app.layout = html.Div([
    # Header
    html.Div([
        html.H1("Command Center"),
        html.P("Todos, incidents & AI assistant in one place"),
    ], className='app-header'),

    # Chat assistant section
    html.Div([
        html.H3("Chat Assistant"),
        html.Div(
            id='chat-messages',
            children=render_chat_messages([]),
            className='chat-window',
        ),
        html.Div([
            dcc.Input(
                id='chat-input',
                type='text',
                placeholder='Ask a question...',
                n_submit=0,
                style={'flex': '1'},
            ),
            html.Button('Send', id='chat-send-button', n_clicks=0,
                         className='btn btn-send'),
        ], className='chat-input-row'),
        dcc.Store(id='chat-history', data=[]),
        dcc.Loading(
            id='chat-loading', type='dot',
            children=html.Div(id='chat-loading-output'),
            style={'marginTop': '5px'},
        ),
    ], className='card'),

    # Add new todo section
    html.Div([
        html.H3("Add New Todo"),
        html.Div([
            dcc.Input(
                id='new-todo-input',
                type='text',
                placeholder='What do you need to do?',
            ),
            html.Button('Add Todo', id='add-todo-button', n_clicks=0,
                         className='btn btn-primary'),
        ], className='add-todo-row'),
        html.Div(id='add-todo-message', style={'marginTop': '10px'}),
    ], className='card'),

    # Todo list section
    html.Div([
        html.H3("Your Todos"),
        html.Div(id='todos-container'),
    ], className='card'),

    # Store for tracking changes
    dcc.Store(id='todos-store'),

    # Incidents section
    html.Div([
        html.H3("Incidents"),
        html.Div(id='incidents-container'),
    ], className='card'),

    # Store for incidents data
    dcc.Store(id='incidents-store'),
], className='app-wrapper')


# --- Chat callbacks ---

@app.callback(
    [Output('chat-messages', 'children'),
     Output('chat-history', 'data'),
     Output('chat-input', 'value'),
     Output('chat-loading-output', 'children')],
    [Input('chat-send-button', 'n_clicks'),
     Input('chat-input', 'n_submit')],
    [State('chat-input', 'value'),
     State('chat-history', 'data')],
    prevent_initial_call=True
)
def handle_chat(n_clicks, n_submit, user_input, chat_history):
    """Send user message to the agent and display the response."""
    if not user_input or not user_input.strip():
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update

    chat_history = chat_history or []
    chat_history.append({"role": "user", "content": user_input.strip()})

    response_text = ask_agent(chat_history)
    chat_history.append({"role": "assistant", "content": response_text})

    return render_chat_messages(chat_history), chat_history, "", ""


# --- Todo callbacks ---

@app.callback(
    Output('todos-store', 'data'),
    [Input('add-todo-button', 'n_clicks'),
     Input('new-todo-input', 'n_submit'),
     Input({'type': 'todo-checkbox', 'index': dash.ALL}, 'value'),
     Input({'type': 'delete-button', 'index': dash.ALL}, 'n_clicks')],
    [State('new-todo-input', 'value')],
    prevent_initial_call=False
)
def manage_todos_store(add_clicks, submit_clicks, checkbox_values, delete_clicks, new_todo):
    """Manage todos store - handles initial load, adding, toggling, and deleting todos."""
    ctx = callback_context

    # Initial load - no triggers
    if not ctx.triggered:
        return get_todos()

    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]

    # Handle adding new todo (both button click and Enter key)
    if (triggered_id == 'add-todo-button' or triggered_id == 'new-todo-input') and new_todo and new_todo.strip():
        if add_todo(new_todo.strip()):
            return get_todos()

    # Handle checkbox toggle
    elif 'todo-checkbox' in triggered_id:
        import json
        try:
            id_dict = json.loads(triggered_id)
            todo_id = id_dict['index']
            if toggle_todo(todo_id):
                return get_todos()
        except:
            pass

    # Handle delete
    elif 'delete-button' in triggered_id:
        import json
        try:
            id_dict = json.loads(triggered_id)
            todo_id = id_dict['index']
            if delete_todo(todo_id):
                return get_todos()
        except:
            pass

    return dash.no_update

@app.callback(
    [Output('todos-container', 'children'),
     Output('add-todo-message', 'children'),
     Output('new-todo-input', 'value')],
    [Input('todos-store', 'data'),
     Input('add-todo-button', 'n_clicks'),
     Input('new-todo-input', 'n_submit')],
    [State('new-todo-input', 'value')]
)
def update_todos_display(todos_data, add_clicks, submit_clicks, new_todo):
    """Update the display of todos and handle add todo messages."""
    ctx = callback_context
    triggered_id = ctx.triggered[0]['prop_id'].split('.')[0] if ctx.triggered else None

    # Handle adding new todo message and clear input (both button click and Enter key)
    if (triggered_id == 'add-todo-button' or triggered_id == 'new-todo-input') and new_todo and new_todo.strip():
        # Clear the input field after adding
        return display_todos(todos_data), "", ""

    return display_todos(todos_data), "", ""

def display_todos(todos_data):
    """Display todos in the UI."""
    if not todos_data:
        return html.Div("No todos yet! Add one above to get started.",
                         className='todo-empty')

    todo_items = []
    for todo_id, task, completed, created_at in todos_data:
        todo_items.append(html.Div([
            dcc.Checklist(
                id={'type': 'todo-checkbox', 'index': todo_id},
                options=[{'label': '', 'value': 'completed'}],
                value=['completed'] if completed else [],
                className='todo-checkbox',
                style={'display': 'inline-block', 'marginRight': '12px'},
            ),
            html.Span(task, className='todo-text-done' if completed else 'todo-text'),
            html.Button("Delete", id={'type': 'delete-button', 'index': todo_id},
                         className='btn btn-delete'),
        ], className='todo-item'))

    return todo_items


# --- Incidents callbacks ---

@app.callback(
    Output('incidents-store', 'data'),
    Input('todos-store', 'data'),
    prevent_initial_call=False
)
def load_incidents(_):
    """Load incidents data on page load."""
    return get_incidents()


@app.callback(
    Output('incidents-container', 'children'),
    Input('incidents-store', 'data')
)
def display_incidents(incidents_data):
    """Render the incidents table."""
    if not incidents_data:
        return html.Div("No incidents found.", className='todo-empty')

    header = html.Thead(html.Tr([
        html.Th("ID"), html.Th("Line ID"), html.Th("Timestamp"),
        html.Th("Severity"), html.Th("Summary"), html.Th("Details"), html.Th("Status"),
    ]))

    severity_class_map = {
        'critical': 'severity-critical',
        'high': 'severity-high',
        'medium': 'severity-medium',
        'low': 'severity-low',
    }

    rows = []
    for inc_id, line_id, ts, severity, summary, details, status in incidents_data:
        sev_cls = severity_class_map.get(str(severity).lower(), 'severity-default')
        rows.append(html.Tr([
            html.Td(inc_id),
            html.Td(line_id),
            html.Td(str(ts)),
            html.Td(html.Span(severity, className=f'severity-badge {sev_cls}')),
            html.Td(summary),
            html.Td(details, style={'maxWidth': '200px', 'overflow': 'hidden',
                                     'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap'}),
            html.Td(status),
        ]))

    return html.Table([header, html.Tbody(rows)], className='incidents-table')


if __name__ == '__main__':
    app.run(debug=True)
