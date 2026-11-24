"""Merge video-worker deltas without overwriting edits saved during inference."""
import copy


class Snapshot(dict):
    def __init__(self, data):
        super().__init__(data)
        self.baseline = copy.deepcopy(data)


MISSING = object()


def clone(value):
    return MISSING if value is MISSING else copy.deepcopy(value)


def merge(base, incoming, current, path=()):
    if incoming == base:
        return clone(current)
    if current == base or current == incoming:
        return clone(incoming)
    if all(isinstance(x, dict) for x in (base, incoming, current)):
        result = {}
        for key in dict.fromkeys([*current, *incoming]):
            value = merge(base.get(key, MISSING), incoming.get(key, MISSING),
                          current.get(key, MISSING), (*path, key))
            if value is not MISSING:
                result[key] = value
        return result
    if all(isinstance(x, list) for x in (base, incoming, current)):
        if path == ('shots',):
            old = {s['id']: s for s in base}
            new = {s['id']: s for s in incoming}
            return [merge(old.get(s['id'], MISSING), new.get(s['id'], MISSING), s,
                          (*path, s['id'])) for s in current]
        if incoming[:len(base)] == base and current[:len(base)] == base:
            result = clone(current)
            for item in incoming[len(base):]:
                if item not in result:
                    result.append(clone(item))
            return result
    # Concurrent edits win same-field conflicts. Render publication separately
    # checks its actual input before treating a take as the current one.
    return clone(current)


def save_data(project, current):
    if not isinstance(project, Snapshot):
        return project
    result = merge(project.baseline, dict(project), current)
    project.baseline = copy.deepcopy(dict(project))
    return result
