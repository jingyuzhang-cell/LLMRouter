"""Drop-in adapter function for a future runner revision. No dispatch code."""
import json
from adapter import adapt,project_slots

def adapt_sink(sink_text,contracts,tid):
    """Same call signature as old runner; reference values not passed to adapt()."""
    try:
        obj=json.loads(sink_text)
        c=contracts[tid]
        sources=c.get('_source_pages',c.get('source_pages'))
        if sources is None:raise ValueError('SOURCE_PAGES_MISSING')
        terminal,diagnostics=adapt(obj,project_slots(c['required_facts']),sources)
        terminal['adapter_diagnostics']=diagnostics
        return terminal
    except (json.JSONDecodeError,ValueError,TypeError,KeyError) as exc:
        return dict(delivery_valid=False,claims_complete=False,claims=[],abstentions=[],
                    abstentions_complete=False,conflict_acknowledgements=[],
                    adapter_diagnostics=[{'reason':'ADAPTER_REJECTED','type':type(exc).__name__}])
