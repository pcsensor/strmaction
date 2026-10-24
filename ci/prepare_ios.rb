require 'xcodeproj'
root = ARGV.fetch(0)
project = Xcodeproj::Project.open(File.join(root, 'Runner.xcodeproj'))
target = project.targets.find { |t| t.name == 'Runner' }
group = project.main_group.find_subpath('Runner', false)
Dir.glob(File.join(root, 'Runner', 'Native', '**', '*.swift')).sort.each do |path|
  ref = group.new_file(path)
  target.source_build_phase.add_file_reference(ref)
end
['UnifiedPlayerPlugin.swift', 'roots.pem'].each do |name|
  ref = group.new_file(File.join(root, 'Runner', name))
  (name.end_with?('.swift') ? target.source_build_phase : target.resources_build_phase).add_file_reference(ref)
end
package = project.new(Xcodeproj::Project::Object::XCRemoteSwiftPackageReference)
package.repositoryURL = 'https://github.com/kingslay/KSPlayer.git'
package.requirement = { 'kind' => 'exactVersion', 'version' => '2.3.4' }
project.root_object.package_references << package
product = project.new(Xcodeproj::Project::Object::XCSwiftPackageProductDependency)
product.package = package
product.product_name = 'KSPlayer'
target.package_product_dependencies << product
build_file = project.new(Xcodeproj::Project::Object::PBXBuildFile)
build_file.product_ref = product
target.frameworks_build_phase.files << build_file
project.build_configurations.each { |c| c.build_settings['IPHONEOS_DEPLOYMENT_TARGET'] = '16.0' }
project.targets.each do |t|
  t.build_configurations.each do |c|
    c.build_settings['IPHONEOS_DEPLOYMENT_TARGET'] = '16.0'
    c.build_settings['PRODUCT_BUNDLE_IDENTIFIER'] = 'top.strmaction.companion' if t == target
    c.build_settings['SWIFT_VERSION'] = '5.10'
    c.build_settings['ENABLE_USER_SCRIPT_SANDBOXING'] = 'NO'
  end
end
project.save
