// Verify or narrowly repair only the exact Panther certificate's private Keychain key.
import Foundation
import Security


func fail(_ stage: String, _ status: OSStatus = errSecParam) -> Never {
    fputs("Panther Keychain verification failed at \(stage) (\(status)).\n", stderr)
    exit(1)
}
guard CommandLine.arguments.count == 4,
      ["check", "inspect", "repair"].contains(CommandLine.arguments[3]) else { fail("arguments") }
let certificatePath = CommandLine.arguments[1]
let helperPath = CommandLine.arguments[2]
let mode = CommandLine.arguments[3]
let helperPartition = "teamid:94KV3E626L" // Pinned official AWS helper developer identity.
let pem = try String(contentsOfFile: certificatePath, encoding: .utf8)
guard let der = Data(base64Encoded: pem.components(separatedBy: .newlines).filter { !$0.hasPrefix("-----") }.joined()),
      let certificate = SecCertificateCreateWithData(nil, der as CFData) else { fail("certificate") }
var identity: SecIdentity?
guard SecIdentityCreateWithCertificate(nil, certificate, &identity) == errSecSuccess,
      let identity = identity else { fail("exact identity") }
var key: SecKey?
guard SecIdentityCopyPrivateKey(identity, &key) == errSecSuccess, let key = key,
      let attributes = SecKeyCopyAttributes(key) as? [String: Any],
      (attributes[kSecAttrIsExtractable as String] as? Bool) == false else { fail("non-extractable key") }
let item = unsafeBitCast(key, to: SecKeychainItem.self)
var keychain: SecKeychain?
guard SecKeychainItemCopyKeychain(item, &keychain) == errSecSuccess, let keychain = keychain else { fail("selected keychain") }
var length: UInt32 = 4096
var pathBuffer = [CChar](repeating: 0, count: Int(length))
guard SecKeychainGetPath(keychain, &length, &pathBuffer) == errSecSuccess,
      let keychainPath = String(validatingUTF8: pathBuffer), keychainPath.hasPrefix("/") else { fail("keychain path") }
var metadata: CFTypeRef?
let query: [String: Any] = [kSecClass as String: kSecClassKey,
                            kSecValueRef as String: key,
                            kSecReturnAttributes as String: true,
                            kSecMatchLimit as String: kSecMatchLimitOne]
guard SecItemCopyMatching(query as CFDictionary, &metadata) == errSecSuccess,
      let attributesForItem = metadata as? [String: Any],
      let label = attributesForItem[kSecAttrLabel as String] as? String,
      label == "Imported Private Key" else { fail("target key label") }
var matches: CFTypeRef?
let search: [String: Any] = [kSecClass as String: kSecClassKey,
                            kSecAttrKeyClass as String: kSecAttrKeyClassPrivate,
                            kSecAttrLabel as String: label,
                            kSecMatchSearchList as String: [keychain],
                            kSecReturnRef as String: true,
                            kSecMatchLimit as String: kSecMatchLimitAll]
guard SecItemCopyMatching(search as CFDictionary, &matches) == errSecSuccess,
      let refs = matches as? [SecKey], refs.count == 1, CFEqual(refs[0], key) else { fail("unique matching key") }

func contents() -> (SecAccess, SecACL?, CFArray?, SecKeychainPromptSelector, [String]) {
    var access: SecAccess?
    guard SecKeychainItemCopyAccess(item, &access) == errSecSuccess, let access = access else { fail("access") }
    var array: CFArray?
    guard SecAccessCopyACLList(access, &array) == errSecSuccess, let acls = array as? [SecACL] else { fail("ACL list") }
    var signingLists = 0
    var partitions: [(SecACL, CFArray?, SecKeychainPromptSelector, [String])] = []
    for acl in acls {
        let authorizations = SecACLCopyAuthorizations(acl) as? [String] ?? []
        var apps: CFArray?
        var description: CFString?
        var selector = SecKeychainPromptSelector()
        guard SecACLCopyContents(acl, &apps, &description, &selector) == errSecSuccess else { fail("ACL contents") }
        if authorizations.contains(kSecACLAuthorizationSign as String) {
            signingLists += 1
            guard let trusted = apps as? [SecTrustedApplication], trusted.count == 1 else { fail("single-helper signing ACL") }
            var applicationData: CFData?
            guard SecTrustedApplicationCopyData(trusted[0], &applicationData) == errSecSuccess,
                  let data = applicationData,
                  String(data: data as Data, encoding: .utf8)?.trimmingCharacters(in: .controlCharacters) == helperPath else {
                fail("exact trusted helper")
            }
        }
        if authorizations.contains(kSecACLAuthorizationPartitionID as String) {
            guard let description = description else { fail("partition description") }
            let hex = description as String
            guard hex.count % 2 == 0, hex.count < 16000 else { fail("partition encoding") }
            var data = Data()
            var offset = hex.startIndex
            while offset < hex.endIndex {
                let end = hex.index(offset, offsetBy: 2)
                guard let byte = UInt8(hex[offset..<end], radix: 16) else { fail("partition hex") }
                data.append(byte)
                offset = end
            }
            guard let dictionary = (try? PropertyListSerialization.propertyList(from: data, format: nil)) as? [String: Any],
                  dictionary.count == 1, let values = dictionary["Partitions"] as? [String],
                  !values.isEmpty, Set(values).count == values.count,
                  values.allSatisfy({ ["apple-tool:", "apple:", helperPartition].contains($0) }) else { fail("bounded partition list") }
            partitions.append((acl, apps, selector, values))
        }
    }
    guard signingLists == 1, partitions.count <= 1 else {
        fputs("Panther ACL counts: signing=\(signingLists), partitions=\(partitions.count).\n", stderr)
        fail("unique signing and partition ACLs")
    }
    let partition = partitions.first
    return (access, partition?.0, partition?.1, partition?.2 ?? SecKeychainPromptSelector(), partition?.3 ?? [])
}

let (access, existingACL, apps, selector, values) = contents()
if mode == "repair" && !values.contains(helperPartition) {
    let data = try PropertyListSerialization.data(fromPropertyList: ["Partitions": values + [helperPartition]], format: .xml, options: 0)
    let hex = data.map { String(format: "%02x", $0) }.joined()
    if let existingACL = existingACL {
        let updated = SecACLSetContents(existingACL, apps, hex as CFString, selector)
        guard updated == errSecSuccess else { fail("update scoped partition", updated) }
    } else {
        var partitionACL: SecACL?
        let created = SecACLCreateWithSimpleContents(access, nil, hex as CFString, SecKeychainPromptSelector(), &partitionACL)
        guard created == errSecSuccess, let partitionACL = partitionACL else { fail("create scoped partition", created) }
        let auth: [String] = [kSecACLAuthorizationPartitionID as String]
        let setAuth = SecACLUpdateAuthorizations(partitionACL, auth as CFArray)
        guard setAuth == errSecSuccess else { fail("partition authorization", setAuth) }
    }
    let persisted = SecKeychainItemSetAccess(item, access)
    guard persisted == errSecSuccess else { fail("persist scoped partition", persisted) }
}
let finalValues = mode == "repair" ? contents().4 : values
if mode != "inspect" && !finalValues.contains(helperPartition) { fail("missing helper developer partition") }
let summary: [String: Any] = ["targetLabel": label,
                              "keychainPath": keychainPath,
                              "partitions": finalValues,
                              "partitionPresent": finalValues.contains(helperPartition)]
let output = try JSONSerialization.data(withJSONObject: summary, options: [.sortedKeys])
guard let text = String(data: output, encoding: .utf8) else { fail("verification output") }
print(text)
