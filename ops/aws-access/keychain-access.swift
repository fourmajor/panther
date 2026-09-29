// Modify only the identity selected by the exact certificate, never an entire Keychain.
import Foundation
import Security

func fail(_ stage: String, _ status: OSStatus = errSecParam) -> Never {
    fputs("Panther Keychain verification failed at \(stage) (\(status)).\n", stderr)
    exit(1)
}
guard CommandLine.arguments.count == 4,
      ["check", "repair"].contains(CommandLine.arguments[3]) else { fail("arguments") }
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

func contents() -> (SecAccess, SecACL, CFArray?, SecKeychainPromptSelector, [String]) {
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
    guard signingLists == 1, partitions.count == 1 else { fail("unique signing and partition ACLs") }
    let partition = partitions[0]
    return (access, partition.0, partition.1, partition.2, partition.3)
}

let (access, partitionACL, apps, selector, values) = contents()
if !values.contains(helperPartition) {
    guard mode == "repair" else { fail("missing helper developer partition") }
    let data = try PropertyListSerialization.data(fromPropertyList: ["Partitions": values + [helperPartition]], format: .xml, options: 0)
    let hex = data.map { String(format: "%02x", $0) }.joined()
    let update = SecACLSetContents(partitionACL, apps, hex as CFString, selector)
    guard update == errSecSuccess else { fail("scoped partition update", update) }
    // Normal OS authorization remains enabled; no password is collected, cached or passed in argv.
    let persist = SecKeychainItemSetAccess(item, access)
    guard persist == errSecSuccess else { fail("persist scoped access", persist) }
}
guard contents().4.contains(helperPartition) else { fail("persisted helper partition") }
print("Verified exact Panther identity: non-extractable key, single-helper signing ACL, approved AWS developer partition.")
