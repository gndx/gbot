// EventKit expands recurring meetings and uses the calendars synced on this Mac.
// This helper only reads events; it never creates, updates or deletes them.
import Foundation
import EventKit

var arguments = Array(CommandLine.arguments.dropFirst())
var outputPath: String?
if let index = arguments.firstIndex(of: "--output"), index + 1 < arguments.count {
    outputPath = arguments[index + 1]
    arguments.removeSubrange(index...(index + 1))
}
let action = arguments.first ?? "status"
let store = EKEventStore()

func respond(_ value: [String: Any], code: Int32 = 0) -> Never {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.sortedKeys])
    if let path = outputPath {
        do {
            try data.write(to: URL(fileURLWithPath: path), options: .atomic)
        } catch {
            exit(1)
        }
    } else {
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([10]))
    }
    exit(code)
}

func accessName() -> String {
    switch EKEventStore.authorizationStatus(for: .event) {
    case .fullAccess: return "authorized"
    case .notDetermined: return "not_determined"
    case .restricted: return "restricted"
    case .writeOnly: return "write_only"
    default: return "denied"
    }
}

if action == "status" {
    respond(["authorization": accessName()])
}
if action == "authorize" {
    if accessName() == "authorized" {
        respond(["authorization": "authorized"])
    }
    store.requestFullAccessToEvents { granted, _ in
        respond(["authorization": granted ? "authorized" : accessName()], code: granted ? 0 : 1)
    }
    RunLoop.main.run()
    exit(1)
}
guard accessName() == "authorized" else {
    respond(["error": "calendar_permission", "authorization": accessName()], code: 1)
}
let allCalendars = store.calendars(for: .event)
if action == "calendars" {
    respond(["calendars": allCalendars.map {
        ["id": $0.calendarIdentifier, "title": $0.title, "source": $0.source.title]
    }])
}
guard action == "next" else {
    respond(["error": "unknown_command"], code: 1)
}
let selectedIDs = Set(arguments.dropFirst())
let calendars = selectedIDs.isEmpty ? allCalendars : allCalendars.filter {
    selectedIDs.contains($0.calendarIdentifier)
}
if !selectedIDs.isEmpty && calendars.count != selectedIDs.count {
    respond(["error": "calendar_missing"], code: 1)
}
let now = Date()
let end = now.addingTimeInterval(7 * 24 * 3600)
let predicate = store.predicateForEvents(withStart: now, end: end, calendars: calendars)
let events = store.events(matching: predicate).filter { event in
    let declined = event.attendees?.contains {
        $0.isCurrentUser && $0.participantStatus == .declined
    } ?? false
    return !event.isAllDay && event.startDate > now && event.status != .canceled
        && event.availability != .free && !declined
}.sorted {
    if $0.startDate == $1.startDate {
        return $0.calendarItemIdentifier < $1.calendarItemIdentifier
    }
    return $0.startDate < $1.startDate
}
guard let event = events.first else {
    respond(["event": NSNull(), "calendar_count": calendars.count])
}
let formatter = DateFormatter()
formatter.locale = Locale(identifier: "en_US_POSIX")
formatter.timeZone = TimeZone.current
formatter.dateFormat = "HH:mm"
respond(["event": ["id": event.calendarItemIdentifier,
                    "start": Int(event.startDate.timeIntervalSince1970),
                    "time": formatter.string(from: event.startDate),
                    "title": event.title ?? "Meeting",
                    "calendar": event.calendar.title],
         "calendar_count": calendars.count, "timezone": TimeZone.current.identifier])
